"""Idempotent sync from League provider DTOs into the application DB."""
from __future__ import annotations

import logging
from datetime import timezone
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (ExternalIdentity, LeagueCompetition, LeagueFixture,
                      LeagueStanding, OfficialPlayerStat, Player, Team, now)
from ..db import SessionLocal
from . import pfs

logger = logging.getLogger(__name__)

TEAM_TYPE = "team"
PLAYER_TYPE = "player"
COMP_TYPE = "competition"

LOGO_EXTS = {"png", "jpg", "jpeg", "webp"}


def _fetch_team_logo(prov, team_dto, local_team: Team) -> None:
    """Self-host the provider's team crest into storage/logos. Best-effort:
    a missing or failing logo never breaks an import, and we only download
    when the local file is absent (keeps re-imports idempotent and cheap)."""
    if not getattr(team_dto, "logo", "") or not hasattr(prov, "fetch_logo"):
        return
    if local_team.logo_path and Path(local_team.logo_path).is_file():
        return
    try:
        blob = prov.fetch_logo(team_dto)
        if not blob:
            return
        suffix = Path(urlsplit(team_dto.logo).path).suffix.lstrip(".").lower()
        ext = suffix if suffix in LOGO_EXTS else "png"
        target = settings.storage_root / "logos" / f"{local_team.id}.{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        local_team.logo_path = str(target)
    except Exception as exc:  # provider blocked/offline: logos are optional
        logger.warning("team logo fetch failed for %s (%s): %s", team_dto.name, team_dto.id, exc)


def now_utc():
    return now()


def _identity(db: Session, provider: str, entity_type: str, external_id: str,
              internal_id: str, *, url: str | None = None, season: str | None = None,
              competition_id: str | None = None) -> ExternalIdentity:
    ident = db.scalar(select(ExternalIdentity).where(
        ExternalIdentity.provider == provider,
        ExternalIdentity.entity_type == entity_type,
        ExternalIdentity.external_id == external_id))
    if not ident:
        ident = ExternalIdentity(provider=provider, entity_type=entity_type,
                                 external_id=external_id, internal_entity_id=internal_id,
                                 external_url=url, season=season, competition_id=competition_id)
        db.add(ident)
    else:
        ident.internal_entity_id = internal_id
        if url:
            ident.external_url = url
        ident.season = season or ident.season
        ident.competition_id = competition_id or ident.competition_id
    ident.last_synced_at = now_utc()
    return ident


def upsert_competition(db: Session, provider: str, comp: pfs.Competition) -> LeagueCompetition:
    row = db.scalar(select(LeagueCompetition).where(
        LeagueCompetition.provider == provider,
        LeagueCompetition.external_id == comp.id,
        LeagueCompetition.season == comp.season))
    if not row:
        row = LeagueCompetition(provider=provider, external_id=comp.id,
                                name=comp.name, season=comp.season, group_name=comp.slug,
                                slug=comp.slug)
        db.add(row)
    else:
        row.name = comp.name
        row.group_name = comp.slug or comp.group_name
    row.last_synced_at = now_utc()
    return row


def import_competition(provider: str, season: str, external_id: str, *,
                       map_team: dict[str, str] | None = None,
                       import_rosters: bool = False, force: bool = False):
    """Sync competition (standings/teams) and optionally rosters. Mutable: writes DB."""
    prov = pfs.PragueFootballAssociationProvider(season=season, force=force)
    comp_dto = prov.get_competition(external_id)
    with SessionLocal() as db:
        comp = upsert_competition(db, provider, comp_dto)
        db.flush()
        for team_dto in comp_dto.teams:
            # Respect mapping: external id -> local team id, else create new local team
            local_team_id = None
            if map_team and team_dto.id in map_team:
                local_team_id = map_team[team_dto.id]
            elif db.scalar(select(ExternalIdentity).where(
                    ExternalIdentity.provider == provider,
                    ExternalIdentity.entity_type == TEAM_TYPE,
                    ExternalIdentity.external_id == team_dto.id)):
                ident = db.scalar(select(ExternalIdentity).where(
                    ExternalIdentity.provider == provider,
                    ExternalIdentity.entity_type == TEAM_TYPE,
                    ExternalIdentity.external_id == team_dto.id))
                local_team_id = ident.internal_entity_id
            if local_team_id:
                local_team = db.get(Team, local_team_id)
            else:
                local_team = Team(name=team_dto.name.strip(), notes=f"Imported {provider} · {season}")
                db.add(local_team)
                db.flush()
                local_team_id = local_team.id
            _identity(db, provider, TEAM_TYPE, team_dto.id, local_team_id,
                      season=season, competition_id=comp.id)
            _fetch_team_logo(prov, team_dto, local_team)
            # upsert standings row
            standing = db.scalar(select(LeagueStanding).where(
                LeagueStanding.competition_id == comp.id,
                LeagueStanding.external_team_id == team_dto.id))
            def num(x):
                try: return int(float(x.replace(",", ".")))
                except Exception: return 0
            if not standing:
                standing = LeagueStanding(competition_id=comp.id,
                                          external_team_id=team_dto.id,
                                          team_name=team_dto.name)
                db.add(standing)
            standing.team_name = team_dto.name
            standing.position = num(team_dto.position)
            standing.played = num(team_dto.played)
            standing.wins = num(team_dto.wins)
            standing.draws = num(team_dto.draws)
            standing.losses = num(team_dto.losses)
            standing.goals_for = num(team_dto.gf)
            standing.goals_against = num(team_dto.ga)
            standing.points = num(team_dto.points)
            standing.yellow_cards = num(team_dto.cards_yellow)
            standing.red_cards = num(team_dto.cards_red)

            if import_rosters:
                roster = prov.get_roster(team_dto.id)
                for entry in roster:
                    player = db.scalar(select(Player).where(
                        Player.team_id == local_team_id, Player.name == entry.name))
                    if not player:
                        player = Player(team_id=local_team_id, name=entry.name,
                                        position="GK" if entry.position_hint != "" else None,
                                        notes=f"Imported {provider} · {season}")
                        db.add(player)
                        db.flush()
                    _identity(db, provider, PLAYER_TYPE, entry.player_id, player.id,
                              season=season, competition_id=comp.id)
                    stat = db.scalar(select(OfficialPlayerStat).where(
                        OfficialPlayerStat.provider == provider,
                        OfficialPlayerStat.player_external_id == entry.player_id,
                        OfficialPlayerStat.season == season))
                    def n(x):
                        try: return int(float(x)) if x else 0
                        except Exception: return 0
                    if not stat:
                        stat = OfficialPlayerStat(provider=provider, player_external_id=entry.player_id,
                                                  team_external_id=team_dto.id, season=season, name=entry.name,
                                                  age=n(entry.age), appearances=n(entry.appearances),
                                                  minutes=n(entry.minutes), goals=n(entry.goals),
                                                  yellow=n(entry.yellow), red=n(entry.red),
                                                  position_hint=entry.position_hint or None)
                        db.add(stat)
                    else:
                        stat.name = entry.name
                        stat.appearances = n(entry.appearances)
                        stat.minutes = n(entry.minutes)
                        stat.goals = n(entry.goals)
                        stat.yellow = n(entry.yellow)
                        stat.red = n(entry.red)
                        stat.age = n(entry.age)
                    stat.player_id = player.id
        comp.last_synced_at = now_utc()
        db.commit()
    return comp_dto


def list_competitions(provider: str, season: str) -> list[pfs.Competition]:
    prov = pfs.PragueFootballAssociationProvider(season=season)
    return prov.list_competitions()


def sync_results(provider: str, season: str, *, team_external_id: str,
                 competition_id: str | None = None, limit: int = 12) -> dict:
    """Import recent official results + detailed match data for a team."""
    prov = pfs.PragueFootballAssociationProvider(season=season)
    results = prov.recent_results(team_external_id, limit=limit)
    saved = 0
    with SessionLocal() as db:
        # Find the DB competition if competition_id provided
        comp_row = None
        if competition_id:
            comp_row = db.scalar(select(LeagueCompetition).where(
                LeagueCompetition.provider == provider,
                LeagueCompetition.external_id == competition_id,
                LeagueCompetition.season == season))
        if not comp_row:
            raise ValueError(f"Competition {competition_id or '(not selected)'} is not imported for season {season}; import it first")
        for res in results:
            has_score = res.home_score is not None and res.away_score is not None
            row = db.scalar(select(LeagueFixture).where(
                LeagueFixture.competition_id == comp_row.id,
                LeagueFixture.external_id == res.id))
            if not row:
                row = LeagueFixture(
                    competition_id=comp_row.id,
                    external_id=res.id,
                    round_label=res.round_label,
                    match_date=res.date or "",
                    home_team=res.home,
                    away_team=res.away,
                    home_external_id="",
                    away_external_id="",
                    status="played" if has_score else "upcoming",
                    home_score=res.home_score,
                    away_score=res.away_score,
                    url=res.url or f"{prov.base}/zapas/{res.id}",
                )
                db.add(row)
            else:
                row.home_score = res.home_score
                row.away_score = res.away_score
                row.status = "played" if has_score else "upcoming"
                row.home_team = res.home
                row.away_team = res.away
                if res.date:
                    row.match_date = res.date
                if res.round_label:
                    row.round_label = res.round_label
            db.flush()
            saved += 1
        db.commit()
    return {"imported": saved, "results": [r.id for r in results]}


def sync_fixtures(provider: str, season: str, *, competition_slug: str,
                  competition_id: str | None = None, team_external_id: str | None = None) -> dict:
    """Import the full fixture round (played + upcoming) for a whole competition."""
    prov = pfs.PragueFootballAssociationProvider(season=season)
    fixtures = prov.get_fixtures(competition_slug)
    saved = 0
    with SessionLocal() as db:
        comp_row = None
        if competition_id:
            comp_row = db.scalar(select(LeagueCompetition).where(
                LeagueCompetition.provider == provider,
                LeagueCompetition.external_id == competition_id,
                LeagueCompetition.season == season))
        if not comp_row:
            # derive from provided slug (contains the numeric id)
            m = pfs.re.compile(r"^(\d+)")
            ext = m.match(competition_slug) if competition_slug else None
            if ext:
                comp_row = db.scalar(select(LeagueCompetition).where(
                    LeagueCompetition.provider == provider,
                    LeagueCompetition.external_id == ext.group(1),
                    LeagueCompetition.season == season))
        if not comp_row:
            return {"imported": 0, "error": "competition not found"}
        for fx in fixtures:
            is_played = getattr(fx, "played", None)
            has_score = fx.home_score is not None and fx.away_score is not None
            fixture_status = getattr(fx, "status", None) or (
                "played" if (is_played if is_played is not None else has_score) else "upcoming")
            row = db.scalar(select(LeagueFixture).where(
                LeagueFixture.competition_id == comp_row.id,
                LeagueFixture.external_id == fx.id))
            if not row:
                row = LeagueFixture(
                    competition_id=comp_row.id,
                    external_id=fx.id,
                    round_label=fx.round_label or "",
                    match_date=fx.date or "",
                    home_team=fx.home,
                    away_team=fx.away,
                    home_external_id=fx.home_external_id or "",
                    away_external_id=fx.away_external_id or "",
                    status=fixture_status,
                    home_score=fx.home_score if fixture_status == "played" else None,
                    away_score=fx.away_score if fixture_status == "played" else None,
                    url=fx.url,
                )
                db.add(row)
            else:
                row.status = fixture_status
                row.home_team = fx.home or row.home_team
                row.away_team = fx.away or row.away_team
                if fx.home_external_id:
                    row.home_external_id = fx.home_external_id
                if fx.away_external_id:
                    row.away_external_id = fx.away_external_id
                if fixture_status == "played" and has_score:
                    row.home_score = fx.home_score
                    row.away_score = fx.away_score
                if fx.date:
                    row.match_date = fx.date
            db.flush()
            saved += 1
        db.commit()
    return {"imported": saved, "fixtures": [f.id for f in fixtures]}


def sync_competition_fixtures(provider: str, season: str, *, competition_external: str, competition_slug: str,
                                 replace_existing: bool = False, rounds: list[int] | None = None) -> dict:
    """Import the full schedule for ONE competition (round-aware). Optionally replaces existing rows."""
    from . import pfs as _pfs
    prov = _pfs.PragueFootballAssociationProvider(season=season)
    fixtures = prov.get_fixtures_rounds(competition_slug, rounds=rounds)
    saved = 0
    with SessionLocal() as db:
        comp = db.scalar(select(LeagueCompetition).where(
            LeagueCompetition.provider == provider,
            LeagueCompetition.external_id == competition_external,
            LeagueCompetition.season == season))
        if not comp:
            return {"imported": 0, "error": "competition not found"}
        if replace_existing:
            db.query(LeagueFixture).filter(LeagueFixture.competition_id == comp.id).delete()
            db.flush()
        for f in fixtures:
            row = db.scalar(select(LeagueFixture).where(
                LeagueFixture.competition_id == comp.id, LeagueFixture.external_id == f.id))
            status = "played" if getattr(f,"played",False) else "upcoming"
            if not row:
                row = LeagueFixture(competition_id=comp.id, external_id=f.id,
                                    round_label=f.round_label or "", match_date=f.date or "",
                                    home_team=f.home, away_team=f.away,
                                    home_external_id=f.home_external_id or "",
                                    away_external_id=f.away_external_id or "",
                                    status=status, home_score=f.home_score if status == "played" else None,
                                    away_score=f.away_score if status == "played" else None, url=f.url)
                db.add(row)
            else:
                row.round_label = f.round_label or row.round_label
                if f.date:
                    row.match_date = f.date
                row.home_team = f.home or row.home_team
                row.away_team = f.away or row.away_team
                row.status = status
                if status == "played":
                    row.home_score = f.home_score
                    row.away_score = f.away_score
            db.flush()
            saved += 1
        db.commit()
    return {"imported": saved, "fixtures": len(fixtures), "competition": competition_external}

def sync_pibfal(season_label: str = "2026/27 Championship", team_slug: str = "galaksia-praha-23",
                local_team_id: str | None = None, season_tag: str = "2026/27") -> dict:
    """Import PIBFAL fixtures/results for the given season label (never mixed)."""
    from . import pibfal
    provider = pibfal.PibfalProvider(season=season_label)
    events = provider.event_list(team_slug=team_slug)
    saved = 0
    with SessionLocal() as db:
        # Use a dedicated competition row for PIBFAL season
        comp = db.scalar(select(LeagueCompetition).where(
            LeagueCompetition.provider == "pibfal",
            LeagueCompetition.external_id == season_tag,
            LeagueCompetition.season == season_tag))
        if not comp:
            comp = LeagueCompetition(provider="pibfal", external_id=season_tag,
                                     name=f"PIBFAL {season_label}", season=season_tag)
            db.add(comp)
            db.flush()
        for ev in events:
            row = db.scalar(select(LeagueFixture).where(
                LeagueFixture.competition_id == comp.id,
                LeagueFixture.external_id == ev.id))
            home_score = away_score = None
            status = "upcoming"
            if ev.played and ev.score:
                parts = ev.score.split("-")
                if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                    home_score, away_score = int(parts[0].strip()), int(parts[1].strip())
                    status = "played"
            if not row:
                row = LeagueFixture(
                    competition_id=comp.id, external_id=ev.id,
                    match_date=ev.date or "", home_team=ev.home, away_team=ev.away,
                    home_external_id=ev.home_external_id or "",
                    away_external_id=ev.away_external_id or "",
                    status=status, home_score=home_score, away_score=away_score, url=ev.url)
                db.add(row)
            else:
                row.status = status
                if home_score is not None:
                    row.home_score = home_score
                    row.away_score = away_score
                if ev.date:
                    row.match_date = ev.date
                row.home_team = ev.home or row.home_team
                row.away_team = ev.away or row.away_team
            db.flush()
            saved += 1
        db.commit()
    return {"imported": saved, "fixtures": [e.id for e in events]}
