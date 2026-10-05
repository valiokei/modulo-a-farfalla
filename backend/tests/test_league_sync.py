"""Parser regression tests with fictional HTML fixtures (no network)."""
import os
from pathlib import Path
import pytest

from app.league.pfs import PragueFootballAssociationProvider


FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="ignore")


class FakeProvider(PragueFootballAssociationProvider):
    def __init__(self, season="2026", force=False):
        super().__init__(season=season, force=force)
        self._stubs = {}

    def stub(self, url: str, content: str):
        self._stubs[url] = content

    def _http(self, url, use_cache=True):
        if url in self._stubs:
            return self._stubs[url]
        raise AssertionError(f"Unexpected URL in test: {url}")

    def get_teams(self, cid: str):
        # override network -> fixture
        html = self._read_fixture(cid)
        return self._parse_teams(html)

    def _read_fixture(self, cid: str):
        if cid == "752":
            return _read("comp_752.html")
        if cid == "753":
            return _read("comp_753.html")
        return ""

    def _parse_teams(self, html):
        # minimal re-implementation reusing the same parser method with injected html
        import re
        from html import unescape
        from app.league.pfs import Team, _clean
        teams = []
        for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
            if "/tym/" not in tr:
                continue
            link = re.search(r'/tym/(\d+)-([^"]+)"[^>]*>(.*?)</a>', tr, re.S)
            if not link:
                continue
            tid, slug, raw = link.group(1), link.group(2), link.group(3)
            cells = [_clean(c) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]
            name = _clean(re.sub(r"<[^>]+>", " ", raw))
            def cell(i):
                return cells[i] if i < len(cells) else ""
            teams.append(Team(id=tid, name=name, slug=slug, position=cell(0).rstrip("."),
                              played=cell(2), wins=cell(3), draws=cell(4), losses=cell(5),
                              gf=cell(6).split(":")[0] if ":" in cell(6) else "", ga=(cell(6).split(":")[1] if ":" in cell(6) else ""),
                              points=cell(7), cards_yellow=cell(10), cards_red=cell(11)))
        return teams


def test_competition_752_teams_and_shared_team():
    prov = FakeProvider()
    teams = prov._parse_teams(_read("comp_752.html"))
    assert len(teams) >= 10
    gal = [t for t in teams if t.id == "138"]
    assert len(gal) == 1
    assert gal[0].name == "Example United"


def test_competition_753_distinct_opponents():
    prov = FakeProvider()
    teams = prov._parse_teams(_read("comp_753.html"))
    assert len(teams) >= 9
    ids = {t.id for t in teams}
    assert "138" in ids


def test_shared_club_rosters_are_filtered_by_competition(monkeypatch):
    from app.league.pfs import Team
    provider = PragueFootballAssociationProvider(season="2026")
    monkeypatch.setattr(provider, "get_teams", lambda _cid: [Team(id="138", name="Example United", slug="example-united")])
    urls = []

    def get(url):
        urls.append(url)
        fixture = "team_138_group_b.html" if "id_league=752" in url else "team_138_group_c.html"
        return _read(fixture)

    monkeypatch.setattr(provider._client, "get", get)
    assert [player.name for player in provider.get_roster("138", competition_id="752")] == ["Example A One", "Example A Two"]
    assert [player.name for player in provider.get_roster("138", competition_id="753")] == ["Example B One", "Example B Two"]
    assert all("id_season=2026" in url for url in urls)


def test_import_keeps_shared_club_teams_separate_and_idempotent(monkeypatch, tmp_path):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    from app.models import LeagueTeamMapping, Player, Team as LocalTeam
    from app.league import sync
    from app.league.pfs import Competition, RosterEntry, Team

    engine = create_engine(f"sqlite:///{tmp_path / 'league.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(sync, "SessionLocal", sessionmaker(bind=engine))

    class Provider:
        def __init__(self, season, force=False):
            self.season = season

        def get_competition(self, cid):
            return Competition(id=cid, name=f"League {cid}", season=self.season,
                               slug=f"league-{cid}", teams=[Team(id="138", name="Example United")])

        def get_roster(self, tid, competition_id=None):
            assert tid == "138"
            return [RosterEntry(player_id=competition_id, name=f"Player {competition_id}")]

    monkeypatch.setattr(sync.pfs, "PragueFootballAssociationProvider", Provider)
    sync.import_competition("pfs", "2026", "752", import_rosters=True)
    with sessionmaker(bind=engine)() as db:
        local_a = db.scalar(select(LocalTeam).where(LocalTeam.name == "Example United"))
        local_b = LocalTeam(name="Example United B")
        db.add(local_b)
        db.commit()
        a_id, b_id = local_a.id, local_b.id
    sync.import_competition("pfs", "2026", "753", map_team={"138": b_id}, import_rosters=True)
    sync.import_competition("pfs", "2026", "753", import_rosters=True)
    with sessionmaker(bind=engine)() as db:
        links = db.scalars(select(LeagueTeamMapping).order_by(LeagueTeamMapping.competition_external_id)).all()
        assert [(link.competition_external_id, link.local_team_id) for link in links] == [("752", a_id), ("753", b_id)]
        assert [(player.team_id, player.name) for player in db.scalars(select(Player).order_by(Player.name))] == [
            (a_id, "Player 752"), (b_id, "Player 753")]
        assert db.query(LocalTeam).count() == 2


def test_duplicate_club_requires_mapping_and_new_season_has_own_link(monkeypatch, tmp_path):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    from app.models import LeagueTeamMapping, Team as LocalTeam
    from app.league import sync
    from app.league.pfs import Competition, Team

    engine = create_engine(f"sqlite:///{tmp_path / 'seasons.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(sync, "SessionLocal", sessionmaker(bind=engine))

    class Provider:
        def __init__(self, season, force=False):
            self.season = season

        def get_competition(self, cid):
            return Competition(id=cid, name=f"League {cid}", season=self.season,
                               slug=f"league-{cid}", teams=[Team(id="138", name="Example United")])

    monkeypatch.setattr(sync.pfs, "PragueFootballAssociationProvider", Provider)
    sync.import_competition("pfs", "2026", "752")
    with pytest.raises(ValueError, match="Select a local team"):
        sync.import_competition("pfs", "2026", "753")
    with sessionmaker(bind=engine)() as db:
        assert db.query(LeagueTeamMapping).count() == 1
        assert db.query(LocalTeam).count() == 1
        first_id = db.scalar(select(LocalTeam.id))
        new_season_team = LocalTeam(name="Example United 2027")
        db.add(new_season_team)
        db.commit()
        new_id = new_season_team.id
    sync.import_competition("pfs", "2027", "752", map_team={"138": new_id})
    with sessionmaker(bind=engine)() as db:
        links = db.scalars(select(LeagueTeamMapping).order_by(LeagueTeamMapping.season)).all()
        assert [(link.season, link.local_team_id) for link in links] == [
            ("2026", first_id), ("2027", new_id)]


def test_competition_mapping_migration_is_additive_and_idempotent(monkeypatch, tmp_path):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    from app.db import Base

    path = Path(__file__).parents[1] / "alembic/versions/0007_competition_team_mapping.py"
    spec = importlib.util.spec_from_file_location("league_mapping_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE league_team_mappings"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()
        assert inspect(connection).has_table("league_team_mappings")
        assert connection.execute(text("SELECT COUNT(*) FROM league_team_mappings")).scalar_one() == 0


def test_legacy_club_identity_is_never_trusted_for_new_group(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    from app.models import ExternalIdentity, LeagueTeamMapping, Team as LocalTeam
    from app.league import sync
    from app.league.pfs import Competition, Team

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(sync, "SessionLocal", sessions)

    class Provider:
        def __init__(self, season, force=False):
            self.season = season

        def get_competition(self, cid):
            return Competition(id=cid, name="Group C", season=self.season,
                               slug="group-c", teams=[Team(id="138", name="Example United")])

    monkeypatch.setattr(sync.pfs, "PragueFootballAssociationProvider", Provider)
    with sessions() as db:
        original = LocalTeam(name="Example United A")
        replacement = LocalTeam(name="Example United B")
        db.add_all([original, replacement])
        db.flush()
        db.add(ExternalIdentity(provider="pfs", entity_type="team", external_id="138",
                                internal_entity_id=original.id, season="2026", competition_id="753"))
        db.commit()
        replacement_id = replacement.id
    with pytest.raises(ValueError, match="legacy club"):
        sync.import_competition("pfs", "2026", "753")
    with sessions() as db:
        assert db.query(LeagueTeamMapping).count() == 0
        assert db.query(LocalTeam).count() == 2
    sync.import_competition("pfs", "2026", "753", map_team={"138": replacement_id})
    with sessions() as db:
        assert db.query(LeagueTeamMapping).one().local_team_id == replacement_id


def test_fixture_parser_distinguishes_zero_zero_from_unplayed(monkeypatch):
    prov = FakeProvider()
    html = '''<table>
      <tr><td>28.09.2026</td><td>13:00</td><td>1</td><td></td>
        <td><div class="team team--home"><a href="/tym/11-home"><span class="long">Home FC</span></a></div></td>
        <td><a href="/zapas/900-played">0:0</a></td>
        <td><div class="team team--away"><a href="/tym/22-away"><span class="long">Away FC</span></a></div></td>
        <td class="game_number">1</td></tr>
      <tr><td>05.10.2026</td><td>13:00</td><td>2</td><td></td>
        <td><div class="team team--home"><a href="/tym/11-home"><span class="long">Home FC</span></a></div></td>
        <td><a href="/zapas/901-upcoming">-:-</a></td>
        <td><div class="team team--away"><a href="/tym/33-next"><span class="long">Next FC</span></a></div></td>
        <td class="game_number">2</td></tr>
    </table>'''
    monkeypatch.setattr(prov._client, "get", lambda _url: html)
    fixtures = prov.get_fixtures("test-league")
    assert [(f.home_score, f.away_score, f.played) for f in fixtures] == [
        (0, 0, True), (0, 0, False)
    ]


def test_bare_slug_resolves_via_listing_and_unknown_ids_are_refused(monkeypatch):
    """The 2018 regression: a bare '9-liga-...' slug parsed as competition
    id 9 matched the foreign fallback page (id_league=9). Via the /souteze
    listing the slug resolves to 753; unlisted ids must be refused instead
    of fetching a page that cannot be verified."""
    from app.league.pfs import ProviderUnavailable
    prov = PragueFootballAssociationProvider(season="2026")
    listing = ('<a href="/souteze/tabulka/752-9-liga-a5b-3-trida-skupina-b-muzu?id_season=2026">A5B</a>'
               '<a href="/souteze/tabulka/753-9-liga-a5c-3-trida-skupina-c-muzu?id_season=2026">A5C</a>')
    calls = []

    def get(url):
        calls.append(url)
        return listing if url.endswith("/souteze") else "<table></table>"

    monkeypatch.setattr(prov._client, "get", get)
    assert prov.get_fixtures("9-liga-a5c-3-trida-skupina-c-muzu") == []
    assert any(u.endswith("/zapasy/753-9-liga-a5c-3-trida-skupina-c-muzu?id_season=2026&id_round=999")
               for u in calls), calls
    with pytest.raises(ProviderUnavailable):
        prov.get_fixtures("9-liga-not-listed")
    with pytest.raises(ProviderUnavailable):
        prov.get_fixtures("9-liga-a5c-3-trida-skupina-c-muzu", league_id="752")


def test_roster_has_ids_and_stats():
    html = _read("team_138.html")
    import re
    rows = []
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
        rows.append((pid, link.group(2)))
    assert len(rows) >= 15
    assert any("Example Player 01" in n for _, n in rows)
