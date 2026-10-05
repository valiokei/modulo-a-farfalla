"""Prague Football Association (fotbalpraha.cz) provider.

The site is server-rendered HTML. Patterns:
  /souteze                 -> competition index (season links)
  /souteze/tabulka/{id}-...?id_season=2026 -> standings table + teams
  /tym/{club_id}-{slug}    -> team page with roster table
  /hrac/{player_id}-{slug} -> player page (stats)
  /zapas/{match_id}-...    -> match page (lineups/events)

Identifiers verified: Galaksia PFS club id 138; competitions 752 (A5B) and
753 (A5C) for season 2026, drawn from cached snapshots.
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from html import unescape
from typing import Iterable
from urllib.parse import urljoin, urlencode

from .fetch import FetchClient, ProviderUnavailable

logger = logging.getLogger(__name__)

BASE = "https://www.fotbalpraha.cz"


@dataclass
class Competition:
    id: str
    name: str
    season: str
    slug: str = ""
    teams: list["Team"] = field(default_factory=list)


@dataclass
class Team:
    id: str
    name: str
    slug: str = ""
    short_name: str = ""
    abbreviation: str = ""
    logo: str = ""
    position: str = ""
    played: str = ""
    wins: str = ""
    draws: str = ""
    losses: str = ""
    gf: str = ""
    ga: str = ""
    points: str = ""
    cards_yellow: str = ""
    cards_red: str = ""


@dataclass
class RosterEntry:
    player_id: str
    name: str
    age: str = ""
    appearances: str = ""
    minutes: str = ""
    goals: str = ""
    yellow: str = ""
    red: str = ""
    position_hint: str = ""


@dataclass
class Fixture:
    id: str
    round: str
    home: str
    away: str
    home_score: str
    away_score: str
    date: str
    status: str
    url: str


@dataclass
class MatchResult:
    id: str
    round_label: str
    date: str
    time: str
    competition_id: str
    venue: str
    attendance: str
    referee: str
    home: str
    away: str
    home_score: int
    away_score: int
    home_ht: int | None = None
    away_ht: int | None = None
    url: str = ""
    home_external_id: str = ""
    away_external_id: str = ""
    played: bool = False
    events: list[dict] = field(default_factory=list)


def _clean(value: str) -> str:
    return " ".join(unescape(value).split())


def leading_competition_id(value: str | None) -> str | None:
    """Numeric competition id from a '753-9-liga-...' slug or a bare '753'."""
    match = re.match(r"(\d+)", value or "")
    return match.group(1) if match else None


def _league_ids_on_page(html: str) -> set[str]:
    return set(re.findall(r"id_league=(\d+)", html))


def _check_league_page(html: str, expected: str | None, url: str, provider: str = "pfs") -> None:
    """Refuse the HTTP-200 fallback pages served for wrong/malformed slugs.

    fotbalpraha.cz answers a bad /souteze/zapasy/ slug with 200 and the page
    of a different competition (observed: a bare `9-liga-...` slug returned the
    A5B page of the 2018 season), which silently imported wrong fixtures.
    """
    if not expected:
        return
    found = _league_ids_on_page(html)
    if found and expected not in found:
        raise ProviderUnavailable(
            f"{provider}: page {url} belongs to id_league={sorted(found)}, not {expected}; refusing fallback page")
    if not found:
        logger.warning("%s: no id_league marker on %s; cannot verify competition page", provider, url)


class PragueFootballAssociationProvider:
    """Concrete provider for fotbalpraha.cz."""

    name = "Prague Football Association"
    provider_key = "pfs"
    base = BASE

    def __init__(self, season: str = "2026", force: bool = False):
        self.season = season
        self._client = FetchClient(provider=self.provider_key, min_interval=1.0,
                                   cache_seconds=6 * 3600, force=force)

    def list_competitions(self) -> list[Competition]:
        html = self._client.get(f"{BASE}/souteze")
        out: dict[str, Competition] = {}
        for match in re.finditer(
            r'href="/souteze/tabulka/(\d+)-([^"?]+)[^"]*"\s*>\s*(.*?)\s*</a>', html, re.S):
            cid, slug, label = match.groups()
            label = _clean(label)
            if not label or ("muži" not in label.lower() and "skupina" not in label.lower()):
                continue
            out.setdefault(cid, Competition(id=cid, name=label, season=self.season, slug=f"{cid}-{slug}"))
        return list(out.values())

    def get_competition(self, cid: str) -> Competition:
        # competition name from listing; teams handled separately
        for comp in self.list_competitions():
            if comp.id == cid:
                comp.teams = self.get_teams(cid)
                return comp
        raise ValueError(f"Competition {cid} not found")

    def standings_url(self, cid: str) -> str:
        listing = self._client.get(f"{BASE}/souteze")
        slug = ""
        m = re.search(rf'/souteze/tabulka/({re.escape(cid)})-([^"?]+)', listing)
        if m:
            slug = m.group(2)
        return f"{BASE}/souteze/tabulka/{cid}-{slug}?id_season={self.season}"

    def resolve_competition_slug(self, cid: str) -> str:
        """Canonical '<id>-<slug>' competition slug from the /souteze listing."""
        listing = self._client.get(f"{BASE}/souteze")
        match = re.search(rf'/souteze/tabulka/{re.escape(cid)}-([^"?]+)', listing)
        if not match:
            raise ProviderUnavailable(f"{self.provider_key}: competition {cid} missing from /souteze listing")
        return f"{cid}-{match.group(1)}"

    def _listing_entries(self) -> list[tuple[str, str]] | None:
        """(id, slug) pairs from the /souteze listing; None when unfetchable."""
        try:
            listing = self._client.get(f"{BASE}/souteze")
        except Exception as exc:
            logger.warning("%s: /souteze listing unavailable for validation: %s",
                           self.provider_key, exc)
            return None
        return re.findall(r'/souteze/tabulka/(\d+)-([^"?]+)', listing)

    def match_competition_slug(self, value: str | None) -> str | None:
        """Competition id for a slug that appears in the /souteze listing.

        Resolves both the canonical '<id>-<slug>' form and the bare slug the
        site's own links use (e.g. '9-liga-a5c-...' -> '753'). A leading
        number alone is never trusted: unknown or unlisted slugs return None
        instead of a guessed id.
        """
        value = (value or "").strip()
        if not value:
            return None
        entries = self._listing_entries() or []
        for cid, slug in entries:
            if value == slug or value == f"{cid}-{slug}":
                return cid
        if re.fullmatch(r"\d+", value) and any(cid == value for cid, _ in entries):
            return value
        return None

    def _verified_expected(self, value: str | None, league_id: str | None) -> str | None:
        """Expected id_league for a page request, refusing unverifiable ids.

        Validates the explicit league_id — or the leading number of `value` —
        against the /souteze listing. This closes the HTTP-200 fallback bug:
        a bare '9-liga-...' slug parses as id 9, and the foreign fallback
        page the site serves for it also reports id_league=9, so only the
        listing can tell them apart. Values without a leading number (e.g.
        test/fixture slugs) keep the old permissive behaviour.
        """
        candidate = str(league_id) if league_id else leading_competition_id(value)
        if not candidate:
            return None
        entries = self._listing_entries()
        if entries is None:
            raise ProviderUnavailable(
                f"{self.provider_key}: cannot fetch the /souteze listing to verify "
                f"competition id {candidate!r} for {value!r}; refusing an unverified page")
        if any(candidate == cid for cid, _ in entries):
            return candidate
        raise ProviderUnavailable(
            f"{self.provider_key}: competition id {candidate!r} from {value!r} is not in "
            f"the /souteze listing; refusing an unverified page")

    def _resolve_requested_competition(self, value: str, league_id: str | None) -> tuple[str, str | None]:
        """Canonical url slug + validated competition id for a page request.

        Bare slugs from the site's own links (e.g. '9-liga-a5c-...') are
        rewritten to the canonical '<id>-<slug>' form. Anything whose id
        cannot be verified against the /souteze listing raises
        ProviderUnavailable instead of fetching a likely fallback page.
        """
        value = (value or "").strip()
        entries = self._listing_entries() or []
        for cid, slug in entries:
            if value == slug or value == f"{cid}-{slug}":
                if league_id and str(league_id) != cid:
                    raise ProviderUnavailable(
                        f"{self.provider_key}: league_id {league_id!r} does not match "
                        f"listing id {cid} for {value!r}")
                return f"{cid}-{slug}", cid
        if re.fullmatch(r"\d+", value):
            for cid, slug in entries:
                if cid == value:
                    return f"{cid}-{slug}", cid
        return value, self._verified_expected(value, league_id)

    def get_teams(self, cid: str) -> list[Team]:
        expected = self._verified_expected(str(cid), None)
        url = self.standings_url(cid)
        html = self._client.get(url)
        _check_league_page(html, expected, url, self.provider_key)
        teams: list[Team] = []
        # Parse each <tr> containing a /tym/ link
        for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
            if "/tym/" not in tr:
                continue
            link = re.search(r'/tym/(\d+)-([^"]+)"[^>]*>(.*?)</a>', tr, re.S)
            if not link:
                continue
            tid, slug, raw_name = link.group(1), link.group(2), link.group(3)
            cells = [_clean(c) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]
            name = _clean(re.sub(r'<[^>]+>', ' ', raw_name))
            inner = link.group(3)
            def grab(cls):
                m = re.search(r'class="%s"[^>]*>(.*?)<' % cls, inner, re.S)
                return _clean(m.group(1)) if m else ""
            short_n = grab('middle')
            abbr = grab('short')
            if not abbr and len(name) >= 3:
                abbr = name[-3:]
            # cells: [pos, FullName Abbreviation, Z, V, R, P, Skore, B, BK, +/-/RG, ...]
            def cell(i: int) -> str:
                return cells[i] if i < len(cells) else ""
            logo = ""
            logo_m = re.search(r'<img[^>]+src="([^"]*team_%s[^"]*)"' % tid, tr)
            if logo_m:
                logo = logo_m.group(1)
            teams.append(Team(
                id=tid, name=name, slug=slug,
                short_name=short_n,
                abbreviation=abbr,
                logo=logo,
                position=cell(0).rstrip("."),
                played=cell(2), wins=cell(3), draws=cell(4), losses=cell(5),
                gf=cell(6).split(":")[0] if ":" in cell(6) else cell(6),
                ga=cell(6).split(":")[1] if ":" in cell(6) else "",
                points=cell(7), cards_yellow=cell(10), cards_red=cell(11),
            ))
        return teams

    def fetch_logo(self, team: Team) -> bytes | None:
        """Download the team crest referenced by the standings page, if any."""
        if not team.logo:
            return None
        return self._client.get_binary(urljoin(BASE, team.logo))

    def get_team(self, tid: str) -> Team:
        for c in self.list_competitions():
            pass
        # resolve team page by enumerating both Galaksia competitions and more broadly
        # Search the two known competition tables for tid -> return that Team
        for cid in ("752", "753"):
            for team in self.get_teams(cid):
                if team.id == tid:
                    return team
        raise ValueError(f"Team {tid} not found in season {self.season}")

    def get_roster(self, tid: str, competition_id: str | None = None) -> list[RosterEntry]:
        html = self._client.get(self.team_url(tid, competition_id=competition_id))
        rows: list[RosterEntry] = []
        seen = set()
        for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
            if "/hrac/" not in tr:
                continue
            link = re.search(r'/hrac/(\d+)-[^"]+"[^>]*>\s*(.*?)</a>', tr, re.S)
            if not link:
                continue
            pid = link.group(1)
            if pid in seen:
                continue
            seen.add(pid)
            cells = [_clean(c) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]
            def cell(i: int) -> str:
                return cells[i] if i < len(cells) else ""
            rows.append(RosterEntry(
                player_id=pid,
                name=_clean(link.group(2)).rstrip("()"),
                age=cell(1),
                appearances=cell(2),
                minutes=cell(3),
                goals=cell(4),
                yellow=cell(5),
                red=cell(6),
            ))
        return rows

    def team_url(self, tid: str, competition_id: str | None = None) -> str:
        # try to find slug from known competitions; fallback to `?season=` page
        slugs: dict[str, str] = {}
        for cid in ((competition_id,) if competition_id else ("752", "753")):
            for team in self.get_teams(cid):
                slugs[team.id] = team.slug
        slug = slugs.get(tid, "")
        url = f"{BASE}/tym/{tid}-{slug}" if slug else f"{BASE}/tym/{tid}"
        params = {"id_season": self.season}
        if competition_id:
            params["id_league"] = competition_id
            params["id_category"] = "1"
        return f"{url}?{urlencode(params)}"

    def recent_results(self, tid: str, limit: int = 10) -> list[MatchResult]:
        """Recent results from the team page form widget (V/P + title with score)."""
        html = self._client.get(self.team_url(tid))
        out: list[MatchResult] = []
        seen = set()
        for m in re.finditer(
            r'<a data-toggle="tooltip"[^>]*href="/zapas/(\d+)-([^"]+)"[^>]*title="([^"]*)"[^>]*>',
            html):
            zap_id, slug, title = m.groups()
            if zap_id in seen or not title:
                continue
            seen.add(zap_id)
            # title: "06.09.2026 - TJ Sokol Královice ... vs Galaksia ... 0:8"
            date = title.split(" - ")[0].strip() if " - " in title else ""
            rest = title.split(" - ", 1)[1] if " - " in title else title
            score_m = re.search(r"(\d+):(\d+)\s*$", rest.strip())
            if not score_m:
                continue
            home_score, away_score = int(score_m.group(1)), int(score_m.group(2))
            # split teams before the trailing score
            body = rest[: score_m.start()].strip()
            teams = body.split(" vs ")
            home, away = (teams[0].strip(), teams[1].strip()) if len(teams) == 2 else (body, "")
            out.append(MatchResult(
                id=zap_id, round_label="", date=date, time="", competition_id="",
                venue="", attendance="", referee="", home=home, away=away,
                home_score=home_score, away_score=away_score,
                url=f"{BASE}/zapas/{zap_id}-{slug}",
            ))
            if len(out) >= limit:
                break
        return out

    def get_match(self, zap_id: str) -> MatchResult:
        url = f"{BASE}/zapas/{zap_id}"
        if zap_id not in url and False:
            pass
        html = self._client.get(url)
        # A bare id without a slug returns the 404 shell; in that case look up
        # the recent-result links (which carry the full slug) and retry.
        if "game__scoreboard-score" not in html:
            for res in self.recent_results("138", limit=20):
                if res.id == zap_id:
                    html = self._client.get(res.url)
                    break
        result = MatchResult(id=zap_id, round_label="", date="", time="",
                             competition_id="", venue="", attendance="", referee="",
                             home="", away="", home_score=0, away_score=0,
                             url=url)

        def clean(s: str) -> str:
            return " ".join(s.split())

        count = re.search(r'game__scoreboard-score">\s*(\d+):(\d+)\s*<span>\((\d+):(\d+)\)</span>', html, re.S)
        if count:
            result.home_score, result.away_score = int(count.group(1)), int(count.group(2))
            result.home_ht, result.away_ht = int(count.group(3)), int(count.group(4))

        comp = re.search(r'/souteze/tabulka/(\d+)-[^"]*"', html)
        if comp:
            result.competition_id = comp.group(1)
        rnd = re.search(r"<b>([123]\.kolo)</b>", html)
        if rnd:
            result.round_label = rnd.group(1)
        info = re.search(r"<b>([a-z]+ \d{1,2}\.\d{2}\.\d{4})</b><b>\s*,\s*(\d{1,2}:\d{2})</b>", html, re.S)
        if info:
            result.date, result.time = info.group(1), info.group(2)
        venue = re.search(r"Hřiště:</span><b>\s*(.*?)</b>", html, re.S)
        if venue:
            result.venue = clean(venue.group(1))
        att = re.search(r"Diváci:</span><b>\s*(\d+)\s*</b>", html, re.S)
        if att:
            result.attendance = att.group(1)
        try:
            result.attendance = re.sub(r"<[^>]+>", "", result.attendance).strip()
        except Exception:
            pass
        ref = re.search(r"Hlavní rozhodčí:</span>\s*<a[^>]*>([^<]+)</a>", html, re.S)
        if ref:
            result.referee = clean(ref.group(1))
        # clean venue (may include an anchor tag)
        result.venue = clean(re.sub(r"<[^>]+>", "", result.venue))

        home_links = re.findall(r'href="/tym/(?:2026/)?\d+-[^"]+"[^>]*>\s*<span class="long">([^<]+)</span>', html, re.S)
        if len(home_links) >= 2:
            result.home = clean(home_links[0])
            result.away = clean(home_links[1])

        # timeline: goals, cards, subs
        i = html.find("Průběh zápasu")
        if i >= 0:
            seg = html[i: i + 8000]
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
                cells = [" ".join(re.sub(r"<[^>]+>", " ", c).split()) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
                if not cells or len(cells) < 3:
                    continue
                home_txt, time_txt, away_txt = cells[0], cells[1], cells[2]
                if time_txt and time_txt != "Čas":
                    result.events.append({"minute": time_txt, "home": home_txt, "away": away_txt})
        return result

    def get_fixtures_rounds(self, competition_id, rounds=None, league_id=None):
        if rounds is None:
            rounds = list(range(1, 19))
        canonical, expected = self._resolve_requested_competition(str(competition_id), league_id)
        out = []
        seen = set()
        for rnd in rounds:
            url = BASE + "/souteze/zapasy/" + canonical + "?id_season=" + self.season + "&id_round=" + str(rnd)
            html = self._client.get(url)
            _check_league_page(html, expected, url, self.provider_key)
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
                if "/zapas/" not in tr or "game_number" not in tr:
                    continue
                tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
                def clean(i):
                    return " ".join(unescape(re.sub(r"<[^>]+>", " ", tds[i])).split()) if i < len(tds) else ""
                if len(tds) < 8:
                    continue
                zap = re.search(r"/zapas/(\d+)-", tr)
                if not zap or zap.group(1) in seen:
                    continue
                home = re.search(r'class="team team--home">.*?<span class="long">([^<]+)</span>', tr, re.S)
                away = re.search(r'class="team team--away">.*?<span class="long">([^<]+)</span>', tr, re.S)
                score = re.search(r'href="/zapas/(\d+)-[^"]+"[^>]*>\s*([0-9]+:[0-9]+|-\s*:-|:-:|-:-)\s*', tr, re.S)
                zap_id = zap.group(1)
                seen.add(zap_id)
                date = clean(0)
                score_txt = (score.group(2) if score else "") or ""
                played = bool(re.match(r"^\d+:\d+$", score_txt.strip().replace(" ", "")))
                hs, as_ = 0, 0
                if played and ":" in score_txt:
                    hs, as_ = int(score_txt.split(":")[0].strip()), int(score_txt.split(":")[1].strip())
                slug = re.search(r'^/zapas/\d+-([A-Za-z0-9-]+)', ("/zapas/" + tr)[tr.find("/zapas/"):])
                home_m = re.search(r'class="team team--home">.*?/tym/([0-9]+)-', tr, re.S)
                away_m = re.search(r'class="team team--away">.*?/tym/([0-9]+)-', tr, re.S)
                out.append(MatchResult(
                    id=zap_id, round_label=str(rnd) + ".kolo", date=date, time=clean(1),
                    competition_id=competition_id, venue="", attendance="", referee="",
                    home=(" ".join(unescape(home.group(1)).split()) if home else ""),
                    away=(" ".join(unescape(away.group(1)).split()) if away else ""),
                    home_score=hs, away_score=as_,
                    home_external_id=home_m.group(1) if home_m else "",
                    away_external_id=away_m.group(1) if away_m else "",
                    url="", played=played, events=[],
                ))
        return out
    def get_fixtures(self, competition_id: str, league_id: str | None = None) -> list[MatchResult]:
        """Whole season of fixtures from the Zápasy page (played + upcoming).

        `id_round=999` is the site's "vše" (all rounds) selector; the plain
        page only shows the current round. The /souteze-listing validation
        rewrites bare slugs to their canonical form and refuses pages whose
        competition cannot be verified (the HTTP-200 fallback bug).
        """
        canonical, expected = self._resolve_requested_competition(competition_id, league_id)
        url = f"{BASE}/souteze/zapasy/{canonical}?id_season={self.season}&id_round=999"
        html = self._client.get(url)
        _check_league_page(html, expected, url, self.provider_key)
        results: list[MatchResult] = []
        seen = set()
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            if "/zapas/" not in tr or "game_number" not in tr:
                continue
            tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
            def clean(i: int) -> str:
                return " ".join(unescape(re.sub(r"<[^>]+>", " ", tds[i])).split()) if tds and i < len(tds) else ""
            def txt(s: str) -> str:
                return " ".join(unescape(s).split())
            if len(tds) < 8:
                continue
            zap = re.search(r"/zapas/(\d+)-", tr)
            if not zap or zap.group(1) in seen:
                continue
            home = re.search(r'class="team team--home">.*?<span class="long">([^<]+)</span>', tr, re.S)
            away = re.search(r'class="team team--away">.*?<span class="long">([^<]+)</span>', tr, re.S)
            score = re.search(r'href="/zapas/(\d+)-[^"]+"[^>]*>\s*([0-9]+:[0-9]+|-\s*:-|:-:|-:-)\s*', tr, re.S)
            zap_id = zap.group(1)
            seen.add(zap_id)
            date = clean(0)
            score_txt = score.group(2) if score else "-:-"
            hs, as_, status = 0, 0, "upcoming"
            if score_txt != "-:-" and ":" in score_txt:
                parts = score_txt.split(":")
                if parts[0].isdigit() and parts[1].isdigit():
                    hs, as_, status = int(parts[0]), int(parts[1]), "played"
            slug = re.search(r"/zapas/\d+-([^\"']+)", tr)
            home_m = re.search(r'class="team team--home">.*?/tym/(\d+)-', tr, re.S)
            away_m = re.search(r'class="team team--away">.*?/tym/(\d+)-', tr, re.S)
            results.append(MatchResult(
                id=zap_id, round_label="", date=date, time=clean(1),
                competition_id=competition_id, venue="", attendance="", referee="",
                home=txt(home.group(1)) if home else "", away=txt(away.group(1)) if away else "",
                home_score=hs, away_score=as_,
                home_external_id=home_m.group(1) if home_m else "",
                away_external_id=away_m.group(1) if away_m else "",
                url=f"{BASE}/zapas/{zap_id}-{slug.group(1) if slug else ''}",
                played=status == "played", events=[],
            ))
        return results
