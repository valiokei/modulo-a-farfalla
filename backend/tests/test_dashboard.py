import asyncio
from datetime import date

# Share test_flow's isolated environment: the app reads DATABASE_URL and
# STORAGE_ROOT once at import, so both modules must agree on a single root.
from test_flow import TEST_ROOT  # noqa: F401  (sets the test environment)

import httpx
from app.dashboard import trend
from app.db import SessionLocal
from app.main import app, lifespan
from app.models import Category, Event, EventPlayer, Match, Player, Role, Team, User, Video
from app.security import hash_password


def test_trend_compares_recent_window_with_the_previous_one():
    result=trend([1,1,1,3,3,3])
    assert result["window"]==3 and result["recent"]==3 and result["previous"]==1 and result["delta"]==2 and result["delta_pct"]==200.0
    assert result["slope"]>0
    assert trend([4])["recent"] is None and trend([4])["slope"] is None  # one match: no trend is invented
    assert trend([0,0,2,2])["delta_pct"] is None  # no percentage against a zero baseline


def _seed():
    from secrets import token_hex
    tag=token_hex(3)
    with SessionLocal() as db:
        cat={c.name:c for c in db.query(Category).all()}
        us=Team(name=f"Us {tag}");a=Team(name=f"Rival A {tag}");b=Team(name=f"Rival B {tag}")
        db.add_all([us,a,b]);db.flush()
        striker=Player(team_id=us.id,name=f"Striker {tag}",shirt_number=9);db.add(striker);db.flush()
        def match(d,home,away,hs,as_,season="2026/27"):
            m=Match(date=d,home_team=home.name,away_team=away.name,home_team_id=home.id,away_team_id=away.id,primary_team_id=us.id,
                    home_score=hs,away_score=as_,season=season,competition="League");db.add(m);db.flush()
            v=Video(match_id=m.id,original_name="x.mp4",original_path="/dev/null",duration=5400);db.add(v);db.flush()
            return m,v
        def ev(m,v,name,team,t,player=None,meta=None,xy=None):
            e=Event(match_id=m.id,video_id=v.id,category_id=cat[name].id,team_id=team.id if team else None,timestamp=t,metadata_=meta or {},
                    pitch_x=xy[0] if xy else None,pitch_y=xy[1] if xy else None);db.add(e);db.flush()
            if player:db.add(EventPlayer(event_id=e.id,player_id=player.id,role="actor"))
            return e
        m1,v1=match(date(2026,9,1),us,a,2,1)            # home win
        ev(m1,v1,"Shot",us,600,striker,xy=(.9,.5));ev(m1,v1,"Goal",us,610,striker);ev(m1,v1,"Goal",us,3000)
        ev(m1,v1,"Pass",us,100,meta={"result":"successful"});ev(m1,v1,"Pass",us,200,meta={"result":"unsuccessful"})
        ev(m1,v1,"Shot",a,1200);ev(m1,v1,"Goal",a,1210)   # opponent events are "against"
        ev(m1,v1,"Tackle",None,1500)                       # unassigned: counted for the primary team by default
        m2,v2=match(date(2026,9,8),b,us,0,0)            # away draw
        ev(m2,v2,"Shot",us,5500)                          # minute 91+ bucket
        m3,v3=match(date(2026,9,15),us,b,None,None)     # no score entered: never counted as a result
        ev(m3,v3,"Pass",us,50,meta={"result":"successful"})
        m4,v4=match(date(2025,5,1),us,a,0,3,season="2025/26")  # other season
        db.commit()
        coach=User(email=f"coach-{tag}@example.com",password_hash=hash_password("coach-pass"),role=Role.coach,team_id=us.id)
        db.add(coach);db.commit()
        return {"us":us.id,"a":a.id,"b":b.id,"striker":striker.id,"coach":coach.email}


async def _dashboard():
    async with lifespan(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        ids=_seed()
        assert (await client.post("/api/auth/login",json={"email":"admin@example.com","password":"test-password"})).status_code==200
        r=await client.get("/api/dashboard/team",params={"team_id":ids["us"],"season":"2026/27"});assert r.status_code==200,r.text
        d=r.json();metric={m["name"]:m for m in d["metrics"]}
        assert d["record"]=={"played":3,"with_score":2,"W":1,"D":1,"L":0,"goals_for":2,"goals_against":1,"points":4,"form":["W","D"]}
        assert [m["location"] for m in d["matches"]]==["home","away","home"] and d["matches"][2]["result"] is None
        assert metric["goals"]["total"]==2 and metric["goals"]["against_total"]==1
        assert metric["shots"]["total"]==4 and metric["shots"]["per_match"]==round(4/3,2)  # Shot+Goal+Goal / Shot / -
        assert metric["tackles"]["total"]==1 and d["unassigned_included"]==1
        assert metric["pass completion %"]["kind"]=="ratio" and metric["pass completion %"]["total"]==round(2/3*100,1)  # pooled, not averaged
        assert {row["bucket"]:row for row in d["minutes"]}["90+"]["for"]==1
        assert d["zones"]["located"]==1 and d["zones"]["counts"][1][5]==1
        assert d["players"][0]["id"]==ids["striker"] and d["players"][0]["events"]==2
        assert set(d["available"]["seasons"])=={"2026/27","2025/26"}

        # Filters: location, result, opponent, last N, player, unassigned.
        assert len((await client.get("/api/dashboard/team",params={"team_id":ids["us"],"location":"away"})).json()["matches"])==1
        assert len((await client.get("/api/dashboard/team",params={"team_id":ids["us"],"result":"L"})).json()["matches"])==1
        assert len((await client.get("/api/dashboard/team",params={"team_id":ids["us"],"opponent_id":ids["b"]})).json()["matches"])==2
        assert [m["date"] for m in (await client.get("/api/dashboard/team",params={"team_id":ids["us"],"last":2})).json()["matches"]]==["2026-09-08","2026-09-15"]
        mine=(await client.get("/api/dashboard/team",params={"team_id":ids["us"],"season":"2026/27","player_id":ids["striker"]})).json()
        assert {m["name"]:m["total"] for m in mine["metrics"]}["goals"]==1 and mine["players"]==[]
        strict=(await client.get("/api/dashboard/team",params={"team_id":ids["us"],"season":"2026/27","include_unassigned":"false"})).json()
        assert {m["name"]:m["total"] for m in strict["metrics"]}["tackles"]==0
        assert (await client.get("/api/dashboard/team",params={"team_id":ids["us"],"player_id":"missing"})).status_code==400
        assert (await client.get("/api/dashboard/team",params={"team_id":ids["us"],"result":"X"})).status_code==422

        # A coach bound to a team cannot read another team's dashboard.
        await client.post("/api/auth/logout")
        assert (await client.post("/api/auth/login",json={"email":ids["coach"],"password":"coach-pass"})).status_code==200
        assert (await client.get("/api/dashboard/team")).json()["team"]["id"]==ids["us"]
        assert (await client.get("/api/dashboard/team",params={"team_id":ids["a"]})).status_code==403


def test_team_dashboard_filters_and_attribution():
    asyncio.run(_dashboard())


def test_official_results_come_only_from_the_explicit_league_mapping():
    from app.dashboard import official_results
    from app.models import LeagueCompetition, LeagueFixture, LeagueTeamMapping
    with SessionLocal() as db:
        team = Team(name="Official Club"); db.add(team); db.flush()
        comp = LeagueCompetition(provider="pfs", external_id="9001", name="Test league", season="2030", raw={}); db.add(comp); db.flush()
        db.add(LeagueTeamMapping(provider="pfs", season="2030", competition_external_id="9001", team_external_id="77", local_team_id=team.id))
        rows = [("1", "05.09.2030 10:00", "77", "Official Club", "5", "Rivals", 2, 0, "played"),
                ("2", "12.09.2030 10:00", "6", "Others", "77", "Official Club", 3, 1, "played"),
                ("3", "19.09.2030 10:00", "77", "Official Club", "8", "Later", None, None, "upcoming"),
                # Same name, no external id: names are never matched.
                ("4", "26.09.2030 10:00", "", "Official Club", "9", "Ghost", 9, 0, "played")]
        for ext, day, hid, home, aid, away, hs, as_, status in rows:
            db.add(LeagueFixture(competition_id=comp.id, external_id=ext, match_date=day, home_external_id=hid, home_team=home,
                                 away_external_id=aid, away_team=away, home_score=hs, away_score=as_, status=status))
        db.commit()
        blocks = official_results(db, team)
    assert len(blocks) == 1
    block = blocks[0]
    assert block["competition"] == "Test league" and block["season"] == "2030"
    assert [(r["opponent"], r["location"], r["goals_for"], r["goals_against"], r["result"]) for r in block["results"]] == [
        ("Rivals", "home", 2, 0, "W"), ("Others", "away", 1, 3, "L")]
    assert [r["opponent"] for r in block["upcoming"]] == ["Later"]
    assert block["record"] == {"played": 2, "W": 1, "D": 0, "L": 1, "goals_for": 3, "goals_against": 3, "form": ["W", "L"], "points": 3}
