"""Migration 0008 (merge duplicate categories) on a populated 0007 database.

Runs in a subprocess so the module-level settings of the other tests (which
bind DATABASE_URL at import) are not disturbed.
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def alembic(database: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}", "PYTHONPATH": str(BACKEND)}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True, capture_output=True)


def database_at_0007(database: Path) -> None:
    """The desktop path for an existing install: current schema, stamped at 0007.

    (Revision 0001 builds from current metadata, so the chain cannot be replayed
    from scratch; the launcher bootstraps fresh databases the same way.)"""
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}", "PYTHONPATH": str(BACKEND)}
    subprocess.run([sys.executable, "-c", "from app.db import Base, engine; from app import models; Base.metadata.create_all(engine)"],
                   cwd=BACKEND, env=env, check=True, capture_output=True)
    alembic(database, "stamp", "0007")
    with sqlite3.connect(database) as db:
        db.execute("drop table if exists category_merges")


def seed(db: sqlite3.Connection) -> dict:
    def category(name, shortcut=None, pre_roll=5.0, enabled=1):
        cid = f"cat-{name}"
        db.execute('insert into categories (id,name,icon,shortcut,"order",enabled,pre_roll,post_roll,metadata_schema) values (?,?,?,?,?,?,?,?,?)',
                   (cid, name, "•", shortcut, 0, enabled, pre_roll, 5.0, "{}"))
        return cid
    ids = {}
    ids["Recovery"] = category("Recovery")
    ids["Ball Recovery"] = category("Ball Recovery", shortcut="r", pre_roll=8.0)
    ids["Pressure"] = category("Pressure", shortcut="x")
    ids["Press"] = category("Press", shortcut="z")
    ids["Penalty Area Entry"] = category("Penalty Area Entry", enabled=0)
    ids["Box Entry"] = category("Box Entry")
    ids["Turnover Forced"] = category("Turnover Forced")  # only the duplicate exists: renamed
    ids["Foul"] = category("Foul")
    db.execute("insert into teams (id,name,season,notes) values ('t1','Home',null,'')")
    db.execute("insert into teams (id,name,season,notes) values ('t2','Away',null,'')")
    db.execute("insert into matches (id,date,home_team,away_team,competition,season,venue,location_type,notes,attacking_direction,created_at,home_team_id,away_team_id,primary_team_id) "
               "values ('m1','2026-01-01','Home','Away','','','','home','','left_to_right','2026-01-01','t1','t2','t1')")
    db.execute("insert into videos (id,match_id,label,original_name,original_path,mime_type,duration,time_offset,status,processing_progress,analyze_after_processing,created_at) "
               "values ('v1','m1','Main','x.mp4','x','video/mp4',60,0,'ready',100,0,'2026-01-01')")
    for n, name in enumerate(["Recovery", "Ball Recovery", "Ball Recovery", "Pressure", "Press", "Box Entry", "Turnover Forced", "Foul"]):
        db.execute("insert into events (id,match_id,video_id,category_id,timestamp,note,tags,metadata,created_at) values (?,?,?,?,?,?,?,?,?)",
                   (f"e{n}", "m1", "v1", ids[name], n, "", "[]", json.dumps({"keep": n}), "2026-01-01"))
    db.execute("insert into templates (id,name,definition) values ('tp','Defensive',?)",
               (json.dumps({"categories": ["Pressure", "Press", "Ball Recovery", "Foul"], "qualifiers": {"Press": {"a": [1]}}}),))
    db.execute("insert into ai_jobs (id,video_id,status,progress,config,created_at) values ('j1','v1','completed',100,'{}','2026-01-01')")
    db.execute("insert into ai_suggestions (id,ai_job_id,timestamp,proposed_category,proposed_players,confidence,status,evidence,corrected_data) "
               "values ('s1','j1',1,'Box Entry','[]',.6,'pending','{}',?)", (json.dumps({"category_id": ids["Press"], "note": "n"}),))
    db.commit()
    return ids


def snapshot(db: sqlite3.Connection) -> dict:
    return {
        "categories": sorted(db.execute('select id,name,shortcut,enabled,pre_roll,post_roll from categories').fetchall()),
        "events": sorted((i, c, json.dumps(json.loads(m), sort_keys=True)) for i, c, m in db.execute("select id,category_id,metadata from events")),
        "templates": [json.loads(d) for (d,) in db.execute("select definition from templates")],
        "suggestions": [(p, json.loads(c)) for p, c in db.execute("select proposed_category,corrected_data from ai_suggestions")],
    }


def test_duplicate_categories_merge_and_restore(tmp_path):
    database = tmp_path / "touchline.db"
    database_at_0007(database)
    with sqlite3.connect(database) as db:
        cols = {r[1] for r in db.execute("pragma table_info(events)")}
        assert "metadata" in cols, cols
        ids = seed(db)
        before = snapshot(db)
    alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as db:
        names = {n: (i, s, e, pre) for i, n, s, e, pre in db.execute("select id,name,shortcut,enabled,pre_roll from categories")}
        assert not {"Ball Recovery", "Press", "Box Entry", "Turnover Forced"} & names.keys()
        # Renamed in place when only the duplicate existed.
        assert names["Forced Turnover"][0] == ids["Turnover Forced"]
        # Configuration carried over: free shortcut and a non-default roll move; a taken shortcut stays;
        # a disabled kept category is re-enabled because its duplicate was in use.
        assert names["Recovery"][1:] == ("r", 1, 8.0)
        assert names["Pressure"][1] == "x"
        assert names["Penalty Area Entry"][2] == 1
        counts = dict(db.execute("select c.name,count(*) from events e join categories c on c.id=e.category_id group by c.name").fetchall())
        assert counts == {"Recovery": 3, "Pressure": 2, "Penalty Area Entry": 1, "Forced Turnover": 1, "Foul": 1}
        merged = {i: json.loads(m) for i, m in db.execute("select id,metadata from events")}
        assert merged["e1"] == {"keep": 1, "merged_from": "Ball Recovery"} and merged["e0"] == {"keep": 0}
        template = json.loads(db.execute("select definition from templates").fetchone()[0])
        assert template["categories"] == ["Pressure", "Recovery", "Foul"]
        assert template["qualifiers"] == {"Pressure": {"a": [1]}}
        proposed, corrected = db.execute("select proposed_category,corrected_data from ai_suggestions").fetchone()
        assert proposed == "Penalty Area Entry" and json.loads(corrected) == {"category_id": ids["Pressure"], "note": "n"}
    alembic(database, "downgrade", "0007")
    with sqlite3.connect(database) as db:
        assert snapshot(db) == before


def test_database_without_duplicates_is_untouched(tmp_path):
    database = tmp_path / "touchline.db"
    database_at_0007(database)
    alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from category_merges").fetchone()[0] == 0
    alembic(database, "downgrade", "0007")


def test_orphan_rows_left_by_unenforced_foreign_keys_are_cleaned(tmp_path):
    database = tmp_path / "touchline.db"
    database_at_0007(database)
    with sqlite3.connect(database) as db:
        seed(db)
        # What a match deletion did while SQLite ignored the foreign keys.
        db.execute("delete from videos"); db.execute("delete from matches")
        db.execute("insert into league_competitions (id,provider,external_id,name,season,raw) values ('c1','pfs','1','L','2026','{}')")
        db.execute("insert into league_fixtures (id,competition_id,external_id,home_team,away_team,status,home_match_id) "
                   "values ('f1','c1','x','A','B','scheduled','m1')")
        db.commit()
        assert db.execute("pragma foreign_key_check").fetchall()
    alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as db:
        assert db.execute("pragma foreign_key_check").fetchall() == []
        assert db.execute("select count(*) from events").fetchone()[0] == 0
        assert db.execute("select count(*) from ai_suggestions").fetchone()[0] == 0
        # SET NULL rule: the fixture stays, only the dangling link is cleared.
        assert db.execute("select home_match_id from league_fixtures where id='f1'").fetchone() == (None,)
        assert db.execute("select count(*) from categories").fetchone()[0] > 0
