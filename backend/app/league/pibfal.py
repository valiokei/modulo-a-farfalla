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


def _clean(s: str) -> str:
    return " ".join(_h.unescape(s).split())


class PibfalProvider:
    name = "PIBFAL"
    provider_key = "pibfal"

    def __init__(self, season: str = TARGET_SEASON, force: bool = False):
        self.season = season
        self._client = FetchClient(provider=self.provider_key, min_interval=1.0,
                                   cache_seconds=6*3600, force=force)

    def event_list(self, team_slug: str = "galaksia-praha-23") -> list[PibfalFixture]:
        html = self._client.get(f"{BASE}/team/{team_slug}/")
        out: list[PibfalFixture] = []
        for tr in re.findall(r'<tr class="sp-row[^"]*"[^>]*>(.*?)</tr>', html, re.S):
            m = re.search(r'data-season" data-label="Season">([^<]+)</td>', tr)
            if not m or _clean(m.group(1)) != self.season:
                continue
            date = re.search(r'<date>([^<]+)</date>', tr)
            home = re.search(r'data-label="Home"[^>]*>.*?>(?:<a[^>]*>)?([^<]+?)(?:</a>)?\s*<', tr, re.S)
            away = re.search(r'data-label="Away"[^>]*>.*?>(?:<a[^>]*>)?([^<]+?)(?:</a>)?\s*<', tr, re.S)
            result = re.search(r'data-label="Time/Results"[^>]*>(?:<a[^>]*>)?\s*(?:<date>&nbsp;([^<]+)</date>)?([^<]*?)(</a>)?\s*</td>', tr, re.S)
            url = re.search(r'href="(https://pibfal\.com/event/[^"]+)"', tr)
            event_slug = re.search(r"/event/([a-z0-9-]+)/", tr) or re.search(r"/event/([a-z0-9-]+)", tr)
            # unique id: use date hash (events have no numeric id exposed)
            fid = re.sub(r"\D", "", (date.group(1) if date else ""))[:14] or (event_slug.group(1)[-24:] if event_slug else "x")
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
                season=self.season,
                home=_clean(home.group(1)) if home else "",
                away=_clean(away.group(1)) if away else "",
                score=score,
                played=played,
                url=url.group(1) if url else "",
            ))
        return out
