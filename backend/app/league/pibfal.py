"""PIBFAL provider (https://pibfal.com) - WordPress/SportsPress event lists.

The team page lists all events across seasons; we strictly filter by season
label so seasons are never mixed:
  - 2026/27 Championship -> target season for Galaksia (11-a-side league)
  - upcoming rows show a local time instead of a score
"""
from __future__ import annotations
import re, html as _h
from dataclasses import dataclass, field
from .fetch import FetchClient

BASE = "https://pibfal.com"
TARGET_SEASON = "2026/27 Championship"


@dataclass
class PibfalFixture:
    id: str
    date: str
    season: str
    home: str
    away: str
    score: str
    played: bool
    home_external_id: str = ""
    away_external_id: str = ""
    url: str = ""
    legacy_id: str = ""


def _clean(s: str) -> str:
    return " ".join(_h.unescape(s).split())


class PibfalProvider:
    name = "PIBFAL"
    provider_key = "pibfal"

    def __init__(self, season: str = TARGET_SEASON, force: bool = False):
        self.season = season
        self._client = FetchClient(provider=self.provider_key, min_interval=1.0,
                                   cache_seconds=6*3600, force=force)

    def standings(self, season_tag: str) -> list[PibfalStanding]:
        """League table of the season from the home page ("Championship 2026/27")."""
        return parse_standings(self._client.get(f"{BASE}/"), season_tag)

    def league_events(self, season_tag: str, fallback_team: str = "galaksia-praha-23") -> tuple[list[PibfalStanding], list[PibfalFixture]]:
        """Every event of the season: SportsPress has no season-wide calendar page,
        so the team pages of all clubs in the league table are merged (deduplicated
        by event URL)."""
        table = self.standings(season_tag)
        slugs = [row.team_id for row in table if row.team_id] or [fallback_team]
        seen: dict[str, PibfalFixture] = {}
        for slug in slugs:
            for ev in self.event_list(slug):
                seen.setdefault(ev.id, ev)
        return table, sorted(seen.values(), key=lambda ev: (ev.date, ev.id))

    def event_list(self, team_slug: str = "galaksia-praha-23") -> list[PibfalFixture]:
        return parse_events(self._client.get(f"{BASE}/team/{team_slug}/"), self.season)


@dataclass
class PibfalStanding:
    team_id: str
    team_name: str
    position: int
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    points: int


def _team_slug(cell: str) -> str:
    m = re.search(r'href="https://pibfal\.com/team/([a-z0-9-]+)/?"', cell)
    return m.group(1) if m else ""


def parse_standings(html: str, season_tag: str) -> list[PibfalStanding]:
    caption = re.search(r'<h4 class="sp-table-caption">\s*Championship\s+' + re.escape(season_tag) + r'\s*</h4>', html)
    if not caption:
        return []
    end = html.find("</table>", caption.end())
    rows: list[PibfalStanding] = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html[caption.end():end], re.S):
        cells = {k: v for k, v in re.findall(r'<td[^>]*data-label="([^"]+)"[^>]*>(.*?)</td>', tr, re.S)}
        if "Club" not in cells:
            continue
        def num(key: str) -> int:
            text = _clean(re.sub(r"<[^>]+>", "", cells.get(key, "")))
            return int(text) if re.fullmatch(r"-?\d+", text) else 0
        rows.append(PibfalStanding(team_id=_team_slug(cells["Club"]), team_name=_clean(re.sub(r"<[^>]+>", " ", cells["Club"])),
                                   position=num("Pos"), played=num("P"), wins=num("W"), draws=num("D"), losses=num("L"),
                                   goals_for=num("F"), goals_against=num("A"), points=num("Pts")))
    return rows


def legacy_event_id(date_text: str) -> str:
    """Fixture id used before events were keyed by their URL slug."""
    return re.sub(r"\D", "", date_text)[:14]


def parse_events(html: str, season: str) -> list[PibfalFixture]:
    out: list[PibfalFixture] = []
    for tr in re.findall(r'<tr class="sp-row[^"]*"[^>]*>(.*?)</tr>', html, re.S):
        m = re.search(r'data-season" data-label="Season">([^<]+)</td>', tr)
        if not m or _clean(m.group(1)) != season:
            continue
        date = re.search(r'<date>([^<]+)</date>', tr)
        home = re.search(r'data-label="Home"[^>]*>.*?>(?:<a[^>]*>)?([^<]+?)(?:</a>)?\s*<', tr, re.S)
        away = re.search(r'data-label="Away"[^>]*>.*?>(?:<a[^>]*>)?([^<]+?)(?:</a>)?\s*<', tr, re.S)
        result = re.search(r'data-label="Time/Results"[^>]*>(?:<a[^>]*>)?\s*(?:<date>&nbsp;([^<]+)</date>)?([^<]*?)(</a>)?\s*</td>', tr, re.S)
        url = re.search(r'href="(https://pibfal\.com/event/[^"]+)"', tr)
        event_slug = re.search(r"/event/([a-z0-9-]+)/", tr) or re.search(r"/event/([a-z0-9-]+)", tr)
        # Events expose no numeric id: the URL slug is unique across the league.
        fid = (event_slug.group(1)[:80] if event_slug else "") or legacy_event_id(date.group(1) if date else "") or "x"
        home_cell = re.search(r'data-label="Home"[^>]*>(.*?)</td>', tr, re.S)
        away_cell = re.search(r'data-label="Away"[^>]*>(.*?)</td>', tr, re.S)
        label_body = (result.group(2) or "") if result else ""
        played = bool(result and re.search(r"\d+\s*-\s*\d+", label_body))
        score = ""
        if played:
            sm = re.search(r"(\d+)\s*-\s*(\d+)", label_body)
            if sm:
                score = f"{sm.group(1)} - {sm.group(2)}"
        out.append(PibfalFixture(
            id=fid,
            date=_clean(date.group(1).split()[0]) if date else "",
            season=season,
            legacy_id=legacy_event_id(date.group(1) if date else ""),
            home=_clean(home.group(1)) if home else "",
            away=_clean(away.group(1)) if away else "",
            score=score,
            played=played,
            home_external_id=_team_slug(home_cell.group(1)) if home_cell else "",
            away_external_id=_team_slug(away_cell.group(1)) if away_cell else "",
            url=url.group(1) if url else "",
        ))
    return out
