"""Coach dashboard: season-level team statistics built from tagged events.

Everything here is derived from events the staff tagged (or AI suggestions a
coach accepted, which are ordinary events). Nothing is estimated: a match with
no tagged events contributes zeros and is reported as such, and the score only
counts when both goals were entered on the match. Official league results are
reported separately (``official``) and never mixed into the tagged statistics.
"""
import re
from collections import Counter
from datetime import date
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload
from .models import Event, EventPlayer, LeagueCompetition, LeagueFixture, LeagueTeamMapping, Match, Player, Team
from .stats import calculate_stats

# Metrics that are ratios/averages: they are recomputed from the pooled events,
# never summed or averaged across matches.
RATIO_METRICS = {"save %", "pass completion %", "conversion rate", "average possession duration"}
TREND_WINDOW = 5  # matches compared: the last N against the N before them
MINUTE_BUCKETS = [(0, 15), (15, 30), (30, 45), (45, 60), (60, 75), (75, 90), (90, None)]
ZONE_COLUMNS, ZONE_ROWS = 6, 3


def trend(values: list[float], window: int = TREND_WINDOW) -> dict:
    """Recent-vs-previous comparison plus a least-squares slope per match."""
    n = len(values)
    k = min(window, n // 2)
    result = {"recent": None, "previous": None, "delta": None, "delta_pct": None, "slope": None, "window": k}
    if n >= 2:
        mean_x = (n - 1) / 2; mean_y = sum(values) / n
        denominator = sum((i - mean_x) ** 2 for i in range(n))
        result["slope"] = round(sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values)) / denominator, 3)
    if k:
        recent = sum(values[-k:]) / k; previous = sum(values[-2 * k:-k]) / k
        result.update(recent=round(recent, 2), previous=round(previous, 2), delta=round(recent - previous, 2),
                      delta_pct=round((recent - previous) / previous * 100, 1) if previous else None)
    return result


def _result(goals_for, goals_against):
    if goals_for is None or goals_against is None: return None
    return "W" if goals_for > goals_against else "L" if goals_for < goals_against else "D"


def _minute_bucket(seconds: float) -> str:
    minute = seconds / 60
    for low, high in MINUTE_BUCKETS:
        if high is None or minute < high: return f"{low}-{high}" if high is not None else f"{low}+"
    return "90+"


def _zone(event: Event):
    if event.pitch_x is None or event.pitch_y is None: return None
    col = min(ZONE_COLUMNS - 1, max(0, int(event.pitch_x * ZONE_COLUMNS)))
    row = min(ZONE_ROWS - 1, max(0, int(event.pitch_y * ZONE_ROWS)))
    return row, col


def _fixture_day(raw: str | None) -> str:
    """Sortable ISO day from the provider's 'dd.mm.yyyy[ hh:mm]' or ISO date."""
    value = (raw or "").strip()
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value)
    if m: return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return value[:10]


def official_results(db: Session, team: Team) -> list[dict]:
    """Official league results of the team, one block per mapped competition.

    Only explicit league mappings (``map_team``) link a club to a local team;
    names are never matched, so an unmapped competition simply does not appear.
    """
    blocks = []
    for mapping in db.scalars(select(LeagueTeamMapping).where(LeagueTeamMapping.local_team_id == team.id)).all():
        comp = db.scalar(select(LeagueCompetition).where(
            LeagueCompetition.provider == mapping.provider, LeagueCompetition.season == mapping.season,
            LeagueCompetition.external_id == mapping.competition_external_id))
        if not comp: continue
        ext = mapping.team_external_id
        if not ext: continue
        fixtures = db.scalars(select(LeagueFixture).where(LeagueFixture.competition_id == comp.id, or_(
            LeagueFixture.home_external_id == ext, LeagueFixture.away_external_id == ext))).all()
        played, upcoming = [], []
        for f in sorted(fixtures, key=lambda f: (_fixture_day(f.match_date), f.match_date or "")):
            home = f.home_external_id == ext
            row = {"id": f.id, "date": f.match_date, "day": _fixture_day(f.match_date), "round": f.round_label,
                   "location": "home" if home else "away", "opponent": f.away_team if home else f.home_team}
            if f.status == "played" and f.home_score is not None and f.away_score is not None:
                gf, ga = (f.home_score, f.away_score) if home else (f.away_score, f.home_score)
                played.append({**row, "goals_for": gf, "goals_against": ga, "result": _result(gf, ga)})
            else:
                upcoming.append(row)
        if not played and not upcoming: continue
        record = {"played": len(played), "W": sum(r["result"] == "W" for r in played),
                  "D": sum(r["result"] == "D" for r in played), "L": sum(r["result"] == "L" for r in played),
                  "goals_for": sum(r["goals_for"] for r in played), "goals_against": sum(r["goals_against"] for r in played),
                  "form": [r["result"] for r in played[-5:]]}
        record["points"] = 3 * record["W"] + record["D"]
        blocks.append({"provider": comp.provider, "competition": comp.name, "season": comp.season,
                       "record": record, "results": played, "upcoming": upcoming})
    return blocks


def build_dashboard(db: Session, team: Team, *, season: str | None = None, competition: str | None = None,
                    date_from: date | None = None, date_to: date | None = None, location: str | None = None,
                    opponent_id: str | None = None, result: str | None = None, last: int | None = None,
                    player_id: str | None = None, include_unassigned: bool = True) -> dict:
    all_matches = db.scalars(select(Match).where(or_(Match.home_team_id == team.id, Match.away_team_id == team.id))
                             .order_by(Match.date, Match.created_at)).all()
    opponents = {}
    for m in all_matches:
        other = m.away_team_id if m.home_team_id == team.id else m.home_team_id
        if other: opponents[other] = m.away_team if m.home_team_id == team.id else m.home_team
    available = {
        "seasons": sorted({m.season for m in all_matches if m.season}, reverse=True),
        "competitions": sorted({m.competition for m in all_matches if m.competition}),
        "opponents": [{"id": k, "name": v} for k, v in sorted(opponents.items(), key=lambda item: item[1].lower())],
        "players": [{"id": p.id, "name": p.name, "shirt_number": p.shirt_number, "position": p.position}
                    for p in sorted(team.players, key=lambda p: (p.shirt_number is None, p.shirt_number or 0, p.name.lower()))],
    }

    def score(m: Match):
        home = m.home_team_id == team.id
        gf, ga = (m.home_score, m.away_score) if home else (m.away_score, m.home_score)
        return gf, ga

    matches = []
    for m in all_matches:
        home = m.home_team_id == team.id
        gf, ga = score(m)
        if season and m.season != season: continue
        if competition and m.competition != competition: continue
        if date_from and m.date < date_from: continue
        if date_to and m.date > date_to: continue
        if location in ("home", "away") and (location == "home") != home: continue
        if opponent_id and (m.away_team_id if home else m.home_team_id) != opponent_id: continue
        if result and _result(gf, ga) != result: continue
        matches.append(m)
    if last: matches = matches[-last:]

    ids = [m.id for m in matches]
    events = db.scalars(select(Event).options(joinedload(Event.category), selectinload(Event.event_players))
                        .where(Event.match_id.in_(ids))).unique().all() if ids else []
    player_events = None
    if player_id:
        player_events = {e.id for e in events if e.player_id == player_id or any(p.player_id == player_id for p in e.event_players)}

    def side(e: Event, m: Match) -> str | None:
        if e.team_id == team.id: return "for"
        if e.team_id and e.team_id == (m.away_team_id if m.home_team_id == team.id else m.home_team_id): return "against"
        if e.team_id is None and include_unassigned and m.primary_team_id == team.id: return "for"
        return None  # another team, or unassigned and not attributable

    by_match = {m.id: m for m in matches}
    sides: dict[str, dict[str, list[Event]]] = {m.id: {"for": [], "against": []} for m in matches}
    unassigned = Counter()
    for e in events:
        m = by_match[e.match_id]; s = side(e, m)
        if s is None: continue
        if e.team_id is None: unassigned[m.id] += 1
        if s == "for" and player_events is not None and e.id not in player_events: continue
        sides[m.id][s].append(e)

    rows, series = [], {}
    for m in matches:
        home = m.home_team_id == team.id; gf, ga = score(m)
        own = calculate_stats(sides[m.id]["for"]); opp = calculate_stats(sides[m.id]["against"])
        for row in own: series.setdefault(row["name"], []).append(row["value"])
        rows.append({
            "id": m.id, "date": m.date.isoformat(), "season": m.season, "competition": m.competition,
            "location": "home" if home else "away", "opponent": m.away_team if home else m.home_team,
            "opponent_id": m.away_team_id if home else m.home_team_id, "goals_for": gf, "goals_against": ga,
            "result": _result(gf, ga), "events": len(sides[m.id]["for"]), "events_against": len(sides[m.id]["against"]),
            "unassigned_events": unassigned[m.id],
            "metrics": {row["name"]: row["value"] for row in own}, "against": {row["name"]: row["value"] for row in opp},
        })

    pooled_for = [e for m in matches for e in sides[m.id]["for"]]
    pooled_against = [e for m in matches for e in sides[m.id]["against"]]
    totals = calculate_stats(pooled_for); against = {row["name"]: row["value"] for row in calculate_stats(pooled_against)}
    n = len(matches)
    metrics = []
    for row in totals:
        ratio = row["name"] in RATIO_METRICS
        metrics.append({
            "name": row["name"], "group": row["group"], "source": row["source"], "kind": "ratio" if ratio else "count",
            "total": row["value"], "per_match": row["value"] if ratio else (round(row["value"] / n, 2) if n else 0),
            "against_total": against.get(row["name"], 0),
            "against_per_match": against.get(row["name"], 0) if ratio else (round(against.get(row["name"], 0) / n, 2) if n else 0),
            "trend": trend(series.get(row["name"], [])), "event_ids": row["event_ids"][:200],
        })

    scored = [r for r in rows if r["result"]]
    record = {"played": n, "with_score": len(scored), "W": sum(r["result"] == "W" for r in scored),
              "D": sum(r["result"] == "D" for r in scored), "L": sum(r["result"] == "L" for r in scored),
              "goals_for": sum(r["goals_for"] for r in scored), "goals_against": sum(r["goals_against"] for r in scored),
              "points": sum(3 if r["result"] == "W" else 1 if r["result"] == "D" else 0 for r in scored),
              "form": [r["result"] for r in scored[-5:]]}

    categories = Counter(e.category.name for e in pooled_for); categories_against = Counter(e.category.name for e in pooled_against)
    minutes = {f"{low}-{high}" if high is not None else f"{low}+": {"for": 0, "against": 0} for low, high in MINUTE_BUCKETS}
    for e in pooled_for: minutes[_minute_bucket(e.timestamp)]["for"] += 1
    for e in pooled_against: minutes[_minute_bucket(e.timestamp)]["against"] += 1
    zones = [[0] * ZONE_COLUMNS for _ in range(ZONE_ROWS)]
    located = 0
    for e in pooled_for:
        cell = _zone(e)
        if cell: zones[cell[0]][cell[1]] += 1; located += 1

    players = []
    if not player_id:
        involvement: dict[str, list[Event]] = {}
        for e in pooled_for:
            people = {p.player_id for p in e.event_players} | ({e.player_id} if e.player_id else set())
            for pid in people: involvement.setdefault(pid, []).append(e)
        names = {p.id: p for p in team.players}
        for pid, items in involvement.items():
            p = names.get(pid) or db.get(Player, pid)
            if not p or p.team_id != team.id: continue
            stats = {row["name"]: row["value"] for row in calculate_stats(items)}
            players.append({"id": pid, "name": p.name, "shirt_number": p.shirt_number, "position": p.position,
                            "events": len(items), "matches": len({e.match_id for e in items}), "metrics": stats,
                            "top_categories": Counter(e.category.name for e in items).most_common(3)})
        players.sort(key=lambda item: -item["events"])

    return {
        "team": {"id": team.id, "name": team.name}, "available": available,
        "applied": {"season": season, "competition": competition, "date_from": date_from.isoformat() if date_from else None,
                    "date_to": date_to.isoformat() if date_to else None, "location": location, "opponent_id": opponent_id,
                    "result": result, "last": last, "player_id": player_id, "include_unassigned": include_unassigned},
        "record": record, "matches": rows, "metrics": metrics,
        "categories": [{"name": k, "for": v, "against": categories_against.get(k, 0)} for k, v in categories.most_common()],
        "minutes": [{"bucket": k, **v} for k, v in minutes.items()],
        "zones": {"rows": ZONE_ROWS, "columns": ZONE_COLUMNS, "counts": zones, "located": located, "total": len(pooled_for)},
        "players": players, "unassigned_included": sum(unassigned.values()) if include_unassigned else 0,
        "official": official_results(db, team),
    }
