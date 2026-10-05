import asyncio
import base64
import os
import subprocess
import tempfile
import json
from pathlib import Path

TEST_ROOT=Path(tempfile.mkdtemp(prefix="touchline-test-"))
os.environ["DATABASE_URL"]=f"sqlite:///{TEST_ROOT/'test.db'}"
os.environ["STORAGE_ROOT"]=str(TEST_ROOT/"storage")
os.environ["SECRET_KEY"]="test-secret"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"]="test-password"
os.environ["MEDIA_ACCELERATION"]="cpu"
os.environ["FFMPEG_THREADS"]="2"

import httpx
from app.main import app, lifespan
from app.db import SessionLocal
from app.models import AIJob, JobStatus


def tiny_video(path:Path):
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=25","-f","lavfi","-i","sine=frequency=440","-t","3","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac",str(path)],check=True,capture_output=True)


def test_complete_workflow(tmp_path,monkeypatch):
    # API regression fixture only. Real model acceptance is a separate explicit
    # run in real_video_acceptance.py, never inferred from this fixture.
    def inference_fixture(proxy, work, progress):
        progress(95,"Finalizing suggestions")
        (work/'suggestions.json').write_text(json.dumps({"elapsed_seconds":0,"predictions":[{"action":"PASS","timestamp":1.2,"confidence":.7,"model":"test-fixture","model_version":"fixture","source":"TEST_FIXTURE"}]}))
        (work/'provenance.json').write_text(json.dumps({"model":"test-fixture"}))
    monkeypatch.setattr('app.jobs.run_spotting_process',inference_fixture)
    asyncio.run(complete_workflow(tmp_path))


def test_saved_drawings_are_in_exported_pixels(tmp_path):
    asyncio.run(saved_drawings_export(tmp_path))


def test_event_window_is_authoritative_for_clip_export(tmp_path):
    asyncio.run(event_window_export(tmp_path))


def test_team_roster_csv_import_is_idempotent_and_validates_before_write():
    asyncio.run(team_roster_csv_import())


async def team_roster_csv_import():
    from secrets import token_hex
    suffix=token_hex(4)
    async with lifespan(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        assert (await client.post('/api/auth/login',json={"email":"admin@example.com","password":"test-password"})).status_code==200
        csv=("team_name,season,player_name,shirt_number,position\n"
             f"CSV Team {suffix},2026/27,Ada {suffix},1,GK\n"
             f"CSV Team {suffix},2026/27,Sam {suffix},8,CM\n").encode()
        first=await client.post('/api/teams/import-csv',files={"file":("roster.csv",csv,"text/csv")})
        assert first.status_code==200,first.text
        assert first.json()["teams_created"]==1 and first.json()["players_created"]==2
        again=await client.post('/api/teams/import-csv',files={"file":("roster.csv",csv,"text/csv")})
        assert again.status_code==200 and again.json()["players_skipped"]==2
        invalid=("team_name,season,player_name\n"
                 f"Should Not Persist {suffix},2026/27,Valid Row\n"
                 ",2026/27,Missing Team\n").encode()
        rejected=await client.post('/api/teams/import-csv',files={"file":("invalid.csv",invalid,"text/csv")})
        assert rejected.status_code==422
        teams=(await client.get('/api/teams')).json()
        assert not any(team["name"]==f"Should Not Persist {suffix}" for team in teams)


async def saved_drawings_export(tmp_path):
    import hashlib
    import numpy as np
    from app.models import Video
    media=tmp_path/"field.mp4"
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=c=green:s=640x360:r=25",
                    "-t","6","-c:v","libx264","-threads","2","-pix_fmt","yuv420p",str(media)],check=True,capture_output=True)
    original_hash=hashlib.sha256(media.read_bytes()).digest()
    async with lifespan(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        assert (await c.post('/api/auth/login',json={"email":"admin@example.com","password":"test-password"})).status_code==200
        match=(await c.post('/api/matches',json={"date":"2026-09-29","home_team":"Ink test","away_team":"Fixture"})).json()
        video=(await c.post(f"/api/matches/{match['id']}/videos",files={"file":("field.mp4",media.read_bytes(),"video/mp4")})).json()
        async def wait(path):
            for _ in range(150):
                state=(await c.get(path)).json()
                if state["status"] in ("completed","failed"):return state
                await asyncio.sleep(.1)
            raise AssertionError("Export did not finish")
        for _ in range(150):
            video=(await c.get(f"/api/matches/{match['id']}")).json()['videos'][0]
            if video['status'] in ('ready','failed'):break
            await asyncio.sleep(.1)
        assert video['status']=='ready',video
        category=(await c.get('/api/categories')).json()[0]
        event=(await c.post(f"/api/matches/{match['id']}/events",json={"video_id":video['id'],"category_id":category['id'],"timestamp":3,"start":1,"end":5,"note":"Saved note"})).json()
        payload={"timestamp":3,"start":2,"end":4,"shapes":[{"type":"pen","color":"#ffdf36","lineWidth":10,"points":[[.2,.25],[.8,.25]]}]}
        ann=(await c.post(f"/api/events/{event['id']}/annotations",json=payload)).json()
        payload['shapes'].append({"type":"pen","color":"#ffdf36","lineWidth":10,"points":[[.2,.35],[.8,.35]]})
        updated=(await c.put(f"/api/annotations/{ann['id']}",json=payload)).json()
        assert updated['start']==2 and updated['end']==4
        assert len((await c.get(f"/api/events/{event['id']}/annotations")).json())==1
        request={"video_id":video['id'],"event_id":event['id'],"start":1,"end":5,"overlay":{"header":"Ink fixture","note":"Saved note"}}
        assert (await c.post('/api/exports/clip',json={**request,"event_id":"missing"})).status_code==400
        job=(await c.post('/api/exports/clip',json=request)).json()
        state=await wait(f"/api/jobs/{job['id']}");assert state['status']=='completed',state
        output=tmp_path/'annotated.mp4';output.write_bytes((await c.get(f"/api/jobs/{job['id']}/download")).content)
        def frame(path,time):
            pixels=subprocess.run(['ffmpeg','-v','error','-ss',str(time),'-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True,timeout=15)
            return np.frombuffer(pixels.stdout,dtype=np.uint8).reshape(360,640,3)
        def yellow(image):return ((image[:,:,0]>180)&(image[:,:,1]>160)&(image[:,:,2]<120)).sum()
        active=frame(output,1.5)
        assert yellow(active[86:96,150:500])>700
        assert yellow(active[121:131,150:500])>700
        assert yellow(frame(output,.5)[:160])==0
        assert yellow(frame(output,3.5)[:160])==0
        clean=(await c.post('/api/exports/clip',json={**request,"overlay":None,"include_annotations":False})).json()
        assert (await wait(f"/api/jobs/{clean['id']}"))['status']=='completed'
        clean_path=tmp_path/'clean.mp4';clean_path.write_bytes((await c.get(f"/api/jobs/{clean['id']}/download")).content)
        assert yellow(frame(clean_path,1.5))==0
        for invalid in (-1,11):
            assert (await c.post('/api/exports/clip',json={**request,"freeze_seconds":invalid})).status_code==422
        frozen=(await c.post('/api/exports/clip',json={**request,"freeze_seconds":3})).json()
        assert (await wait(f"/api/jobs/{frozen['id']}"))['status']=='completed'
        frozen_path=tmp_path/'frozen.mp4';frozen_path.write_bytes((await c.get(f"/api/jobs/{frozen['id']}/download")).content)
        from app.media import probe
        assert abs(float(probe(frozen_path)['format']['duration'])-7)<.15
        assert yellow(frame(frozen_path,1)[:160])==0
        assert yellow(frame(frozen_path,3)[:160])>1400
        assert yellow(frame(frozen_path,5.5)[:160])==0
        # The reported bug: the pause must appear even when the event has no saved
        # drawings -- it anchors to the event timestamp, not to a drawing frame.
        bare_event=(await c.post(f"/api/matches/{match['id']}/events",json={"video_id":video['id'],"category_id":category['id'],"timestamp":3,"start":1,"end":5})).json()
        bare=(await c.post('/api/exports/clip',json={**request,"event_id":bare_event['id'],"overlay":None,"freeze_seconds":3})).json()
        assert (await wait(f"/api/jobs/{bare['id']}"))['status']=='completed'
        bare_path=tmp_path/'bare.mp4';bare_path.write_bytes((await c.get(f"/api/jobs/{bare['id']}/download")).content)
        assert abs(float(probe(bare_path)['format']['duration'])-7)<.15
        # Camera offsets must not move either the clip or its saved pause.
        assert (await c.patch(f"/api/videos/{video['id']}?time_offset=10")).status_code==200
        offset_event=(await c.post(f"/api/matches/{match['id']}/events",json={"video_id":video['id'],"category_id":category['id'],"timestamp":13})).json()
        assert offset_event['start']>=10 and offset_event['end']<=16 and offset_event['end']>13
        with SessionLocal() as db:
            from app.models import Event, Annotation
            stored_event=db.get(Event,event['id']);stored_event.start=11;stored_event.end=15;stored_event.timestamp=13
            stored_annotation=db.get(Annotation,ann['id']);stored_annotation.timestamp=13;stored_annotation.start=12;stored_annotation.end=14
            db.commit()
        offset_export=(await c.post('/api/exports/clip',json={**request,"start":11,"end":15,"freeze_seconds":3})).json()
        assert (await wait(f"/api/jobs/{offset_export['id']}"))['status']=='completed'
        offset_path=tmp_path/'offset.mp4';offset_path.write_bytes((await c.get(f"/api/jobs/{offset_export['id']}/download")).content)
        assert yellow(frame(offset_path,3)[:160])>1400
        playlist=(await c.post(f"/api/matches/{match['id']}/playlists",json={"name":"Drawings","event_ids":[event['id']]})).json()
        highlight=(await c.post(f"/api/playlists/{playlist['id']}/export")).json()
        assert (await wait(f"/api/jobs/{highlight['id']}"))['status']=='completed'
        highlight_path=tmp_path/'highlight.mp4';highlight_path.write_bytes((await c.get(f"/api/jobs/{highlight['id']}/download")).content)
        assert yellow(frame(highlight_path,1.5)[:160])>1400
        with SessionLocal() as db: stored=Path(db.get(Video,video['id']).original_path)
        assert hashlib.sha256(stored.read_bytes()).digest()==original_hash
        assert not list((stored.parent.parent/'clips').glob('*-ink-*'))


async def complete_workflow(tmp_path):
    media=tmp_path/"test.mp4";tiny_video(media)
    async with lifespan(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        assert (await c.post("/api/auth/login",json={"email":"admin@example.com","password":"test-password"})).status_code==200
        team=(await c.post("/api/teams",json={"name":"City Amateur"})).json()
        player=(await c.post(f"/api/teams/{team['id']}/players",json={"name":"Alex","shirt_number":1,"position":"GK"})).json()
        player=(await c.put(f"/api/players/{player['id']}",json={"name":"Alex Keeper","shirt_number":1,"position":"GK","notes":"Captain","active":True})).json();assert player["name"]=="Alex Keeper"
        reserve=(await c.post(f"/api/teams/{team['id']}/players",json={"name":"Temporary","shirt_number":99,"position":"ST"})).json();assert (await c.delete(f"/api/players/{reserve['id']}")).status_code==204
        midfielder=(await c.post(f"/api/teams/{team['id']}/players",json={"name":"Sam","shirt_number":8,"position":"CM"})).json()
        receiver=(await c.post(f"/api/teams/{team['id']}/players",json={"name":"Jo","shirt_number":10,"position":"AM"})).json()
        opponent=(await c.post("/api/teams",json={"name":"United","season":"2026/27","notes":"Recurring opponent"})).json()
        defender=(await c.post(f"/api/teams/{opponent['id']}/players",json={"name":"Taylor","shirt_number":4,"position":"CB"})).json()
        template=next(x for x in (await c.get("/api/templates")).json() if x["name"]=="Full Match")
        match=(await c.post("/api/matches",json={"date":"2026-09-17","home_team_id":team["id"],"away_team_id":opponent["id"],"primary_team_id":team["id"],"competition":"League","season":"2026/27","venue":"Community Ground","location_type":"home","template_id":template["id"],"notes":"","attacking_direction":"left-to-right","squad":[{"player_id":midfielder["id"],"role":"CM","starter":True},{"player_id":receiver["id"],"role":"AM","starter":True}]})).json()
        assert match["home_team"]=="City Amateur" and len(match["squad"])==2
        match_payload={"date":"2026-09-17","home_team_id":team["id"],"away_team_id":opponent["id"],"primary_team_id":team["id"],"competition":"Cup","season":"2026/27","venue":"Community Ground","location_type":"home","template_id":template["id"],"notes":"Edited","attacking_direction":"left-to-right","squad":[{"player_id":midfielder["id"],"role":"CM","starter":True},{"player_id":receiver["id"],"role":"AM","starter":True}]}
        match=(await c.put(f"/api/matches/{match['id']}",json=match_payload)).json();assert match["competition"]=="Cup"
        disposable=(await c.post("/api/matches",json={**match_payload,"date":"2026-09-18","competition":"Delete me","squad":[]})).json();assert (await c.delete(f"/api/matches/{disposable['id']}")).status_code==204
        disposable_team=(await c.post("/api/teams",json={"name":"Delete FC"})).json();assert (await c.delete(f"/api/teams/{disposable_team['id']}")).status_code==204
        r=await c.post(f"/api/matches/{match['id']}/videos",files={"file":("test.mp4",media.read_bytes(),"video/mp4")},data={"label":"Main","time_offset":"0","analyze_ai":"true"})
        assert r.status_code==200
        for _ in range(100):
            video=(await c.get(f"/api/matches/{match['id']}")).json()["videos"][0]
            if video["status"] in ("ready","failed"):break
            await asyncio.sleep(.1)
        assert video["status"]=="ready" and video["processing_progress"]==100 and video["analyze_after_processing"],video.get("error")
        automatic={}
        for _ in range(100):
            automatic_response=await c.get(f"/api/videos/{video['id']}/ai-job")
            if automatic_response.status_code==200:
                automatic=automatic_response.json()
                if automatic["status"] in ("completed","failed"):break
            await asyncio.sleep(.1)
        assert automatic.get("status")=="completed",automatic.get("error")
        assert (await c.get(f"/api/videos/{video['id']}/stream",headers={"Range":"bytes=0-99"})).status_code==206
        category=next(x for x in (await c.get("/api/categories")).json() if x["name"]=="Save")
        event_payload={"video_id":video["id"],"category_id":category["id"],"timestamp":1.2,"note":"","tags":[],"metadata":{},"player_id":player["id"],"pitch_x":.2,"pitch_y":.4}
        with SessionLocal() as db:
            automatic_job=db.get(AIJob,automatic["id"]);automatic_job.status=JobStatus.running;db.commit()
        assert (await c.post(f"/api/matches/{match['id']}/events",json=event_payload)).status_code==409
        locked_video=(await c.get(f"/api/matches/{match['id']}")).json()["videos"][0]
        assert locked_video["ai_status"]=="running" and locked_video["ai_progress"]==100
        with SessionLocal() as db:
            automatic_job=db.get(AIJob,automatic["id"]);automatic_job.status=JobStatus.completed;db.commit()
        event=(await c.post(f"/api/matches/{match['id']}/events",json=event_payload)).json()
        assert (await c.patch(f"/api/events/{event['id']}",json={"note":"Strong low save","tags":["first-half"]})).json()["note"]=="Strong low save"
        filtered=(await c.get(f"/api/matches/{match['id']}/events",params={"category":category["id"],"q":"low","tag":"first-half"})).json();assert len(filtered)==1
        pass_category=next(x for x in (await c.get("/api/categories")).json() if x["name"]=="Pass")
        pass_event=(await c.post(f"/api/matches/{match['id']}/events",json={"video_id":video["id"],"category_id":pass_category["id"],"timestamp":2,"team_id":team["id"],"players":[{"player_id":midfielder["id"],"role":"actor"},{"player_id":receiver["id"],"role":"receiver"}],"note":"Breaks first line","tags":["build-up"],"metadata":{"result":"successful","direction":"forward"},"pitch_x":.35,"pitch_y":.55})).json()
        assert {x["role"] for x in pass_event["players"]}=={"actor","receiver"}
        stats=(await c.get(f"/api/matches/{match['id']}/stats")).json();assert next(x for x in stats if x["name"]=="completed passes")["value"]==1
        assert (await c.post(f"/api/events/{event['id']}/annotations",json={"timestamp":1.2,"shapes":[{"type":"arrow","x1":.1,"y1":.1,"x2":.5,"y2":.5,"color":"#ffff00"}]})).status_code==200
        calibration=(await c.post(f"/api/videos/{video['id']}/calibrations",json={"timestamp":0,"image_points":[[0,0],[1,0],[1,1],[0,1]],"pitch_points":[[0,0],[1,0],[1,1],[0,1]]})).json();assert calibration["homography"]
        tracking=(await c.post("/api/tracking/jobs",json={"video_id":video["id"],"start":0,"end":2,"config":{"mode":"manual-fallback"},"tracks":[{"player_id":midfielder["id"],"anonymous_id":"track-8","team_id":team["id"],"keyframes":[{"t":0,"x":.2,"y":.3},{"t":2,"x":.4,"y":.35}]},{"player_id":receiver["id"],"anonymous_id":"track-10","team_id":team["id"],"keyframes":[{"t":0,"x":.5,"y":.4},{"t":2,"x":.6,"y":.45}]},{"player_id":defender["id"],"anonymous_id":"track-4","team_id":opponent["id"],"keyframes":[{"t":0,"x":.7,"y":.3},{"t":2,"x":.65,"y":.35}]},{"anonymous_id":"track-x","keyframes":[{"t":0,"x":.8,"y":.6},{"t":2,"x":.75,"y":.55}]}]})).json();assert len(tracking["tracks"])==4
        corrected=(await c.patch(f"/api/tracks/{tracking['tracks'][0]['id']}",json={"player_id":midfielder["id"],"anonymous_id":"track-8","team_id":team["id"],"confidence":1,"keyframes":[{"t":0,"x":.2,"y":.3},{"t":1,"x":.33,"y":.34},{"t":2,"x":.4,"y":.35}],"lost_ranges":[]})).json();assert len(corrected["keyframes"])==3
        playlist=(await c.post(f"/api/matches/{match['id']}/playlists",json={"name":"Saves","event_ids":[event["id"]]})).json()
        assert (await c.get(f"/api/matches/{match['id']}/stats")).json()[1]["value"]==1
        assert "Strong low save" in (await c.get(f"/api/matches/{match['id']}/export.csv")).text
        job=(await c.post("/api/exports/clip",json={"video_id":video["id"],"start":0,"end":2,"overlay":"Save"})).json()
        for _ in range(100):
            state=(await c.get(f"/api/jobs/{job['id']}")).json()
            if state["status"] in ("completed","failed"):break
            await asyncio.sleep(.1)
        assert state["status"]=="completed",state.get("error")
        assert (await c.get(f"/api/jobs/{job['id']}/download")).status_code==200
        presentation=(await c.post("/api/presentations",json={"name":"Team review","notes":"Build-up and saves","items":[{"event_id":pass_event["id"],"order":0,"kind":"clip","title":"Progression"},{"event_id":event["id"],"order":1,"kind":"clip","title":"Goalkeeping"}]})).json();assert len(presentation["items"])==2
        highlight=(await c.post(f"/api/playlists/{playlist['id']}/export")).json()
        for _ in range(100):
            state=(await c.get(f"/api/jobs/{highlight['id']}")).json()
            if state["status"] in ("completed","failed"):break
            await asyncio.sleep(.1)
        assert state["status"]=="completed",state.get("error")
        ai=(await c.post("/api/ai/jobs",json={"video_id":video["id"],"config":{}})).json()
        for _ in range(100):
            state=(await c.get(f"/api/ai/jobs/{ai['id']}")).json()
            if state["status"] in ("completed","failed"):break
            await asyncio.sleep(.1)
        assert state["status"]=="completed",state.get("error")
        suggestion=state["suggestions"][0]
        assert (await c.post(f"/api/ai/suggestions/{suggestion['id']}",json={"action":"edit","category_id":pass_category["id"],"team_id":team["id"],"players":[{"player_id":midfielder["id"],"role":"actor"}],"timestamp":1.5,"metadata":{"result":"successful"},"note":"Corrected by coach"})).json()["corrected_data"]["timestamp"]==1.5
        assert (await c.post(f"/api/ai/suggestions/{suggestion['id']}",json={"action":"accept"})).json()["status"]=="accepted"
        ai_latest=(await c.get(f"/api/videos/{video['id']}/ai-job")).json()
        accepted_proposal=next(x for x in ai_latest["suggestions"] if x["status"]=="accepted")
        assert accepted_proposal["accepted_event_id"]
        matches_view=(await c.get(f"/api/matches/{match['id']}/events")).json()
        assert any(x.get("id")==accepted_proposal["accepted_event_id"] for x in matches_view)
        suggestions_view=(await c.get(f"/api/matches/{match['id']}/events?include_suggestions=1")).json()
        assert any(x.get("ai") and x.get("accepted_event_id")==accepted_proposal["accepted_event_id"] for x in suggestions_view)
        assert all(x["video_id"]==video["id"] and x["match_id"]==match["id"] for x in suggestions_view if x.get("ai"))
        ai2=(await c.post("/api/ai/jobs",json={"video_id":video["id"],"config":{}})).json()
        for _ in range(100):
            state=(await c.get(f"/api/ai/jobs/{ai2['id']}")).json()
            if state["status"] in ("completed","failed"):break
            await asyncio.sleep(.1)
        suggestion=state["suggestions"][0]
        assert (await c.post(f"/api/ai/suggestions/{suggestion['id']}",json={"action":"reject"})).json()["status"]=="rejected"


def test_user_administration():
    # User directory regressions: create validation, partial PATCH, delete with
    # event attribution kept (creator nulled instead of losing analysis data).
    asyncio.run(user_administration())


async def user_administration():
    media=Path(tempfile.mkdtemp(prefix="touchline-users-"))/"clip.mp4";tiny_video(media)
    async with lifespan(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as admin, httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as temp:
        assert (await admin.post("/api/auth/login",json={"email":"admin@example.com","password":"test-password"})).status_code==200
        assert (await admin.post("/api/users",json={"email":"no-pass@x.it","role":"coach"})).status_code==422
        assert (await admin.post("/api/users",json={"email":"not-an-email","password":"12345678"})).status_code==422
        assert (await admin.post("/api/users",json={"email":"admin@example.com","password":"12345678"})).status_code==409
        teams=(await admin.get("/api/teams")).json()
        if len(teams)<2: teams=[(await admin.post("/api/teams",json={"name":"Users Home"})).json(),(await admin.post("/api/teams",json={"name":"Users Away"})).json()]
        team=teams[0]
        players=team.get("players") or []
        if not players: players=[(await admin.post(f"/api/teams/{team['id']}/players",json={"name":"Num Nine","shirt_number":9,"position":"ST"})).json()]
        coach=(await admin.post("/api/users",json={"email":"elena.coach@x.it","password":"secret123","role":"coach","name":"Elena","team_id":team["id"]})).json()
        assert coach["name"]=="Elena" and coach["role"]=="coach" and coach["team"]["id"]==team["id"]
        player_user=(await admin.post("/api/users",json={"email":"num9@x.it","password":"secret123","role":"player","player_id":players[0]["id"]})).json()
        assert player_user["player"]["id"]==players[0]["id"]
        patched=(await admin.patch(f"/api/users/{coach['id']}",json={"name":"Elena M."})).json()
        assert patched["name"]=="Elena M." and patched["email"]=="elena.coach@x.it" and patched["role"]=="coach" and patched["team"]["id"]==team["id"]
        assert (await admin.patch(f"/api/users/{coach['id']}",json={"email":"num9@x.it"})).status_code==409
        short_patch=await admin.patch(f"/api/users/{coach['id']}",json={"name":"Pedro","team_id":teams[1]["id"],"password":"short"})
        assert short_patch.status_code==422
        detail=short_patch.json()["detail"];assert isinstance(detail,str) and "password" in detail and "at least 8" in detail  # regression: detail must be a client-readable string (an array rendered as "[object Object]")
        combined=(await admin.patch(f"/api/users/{coach['id']}",json={"name":"Elena Coach","team_id":teams[1]["id"],"password":"brandnew123"})).json()
        assert combined["name"]=="Elena Coach" and combined["team"]["id"]==teams[1]["id"]  # the reported scenario: name+team+password in one PATCH
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as probe:
            assert (await probe.post("/api/auth/login",json={"email":"elena.coach@x.it","password":"brandnew123"})).status_code==200
            assert (await probe.post("/api/auth/login",json={"email":"elena.coach@x.it","password":"secret123"})).status_code==401
        me=(await admin.get("/api/auth/me")).json()
        assert (await admin.patch(f"/api/users/{me['id']}",json={"role":"coach"})).status_code==400
        assert (await admin.delete(f"/api/users/{me['id']}")).status_code==400
        temp_admin=(await admin.post("/api/users",json={"email":"temp.admin@x.it","password":"tempadmin1","role":"admin","name":"Temp Admin"})).json()
        assert (await temp.post("/api/auth/login",json={"email":"temp.admin@x.it","password":"tempadmin1"})).status_code==200
        template=next(x for x in (await temp.get("/api/templates")).json() if x["name"]=="Full Match")
        match=(await temp.post("/api/matches",json={"date":"2026-09-24","home_team_id":teams[0]["id"],"away_team_id":teams[1]["id"],"primary_team_id":teams[0]["id"],"competition":"","season":"","venue":"","location_type":"home","template_id":template["id"],"notes":"","attacking_direction":"left-to-right","squad":[]})).json()
        await temp.post(f"/api/matches/{match['id']}/videos",files={"file":("clip.mp4",media.read_bytes(),"video/mp4")},data={"label":"Temp","time_offset":"0","analyze_ai":"false"})
        for _ in range(100):
            video=(await temp.get(f"/api/matches/{match['id']}")).json()["videos"][0]
            if video["status"] in ("ready","failed"):break
            await asyncio.sleep(.1)
        assert video["status"]=="ready"
        category=next(x for x in (await temp.get("/api/categories")).json() if x["name"]=="Goal")
        event=(await temp.post(f"/api/matches/{match['id']}/events",json={"video_id":video["id"],"category_id":category["id"],"timestamp":1.5})).json()
        assert event["creator_id"]==temp_admin["id"]
        assert (await admin.delete(f"/api/users/{temp_admin['id']}")).status_code==204
        assert not any(u["id"]==temp_admin["id"] for u in (await admin.get("/api/users")).json())
        assert (await admin.get(f"/api/matches/{match['id']}/events")).json()[0]["creator_id"] is None
        assert (await admin.delete(f"/api/users/{coach['id']}")).status_code==204
        assert (await admin.delete(f"/api/users/{player_user['id']}")).status_code==204
        assert (await admin.delete(f"/api/matches/{match['id']}")).status_code==204


def test_team_logos():
    # Logo regressions: upload validation, private logo_path, serve, replace,
    # remove and file cleanup on team delete.
    asyncio.run(team_logos())


async def team_logos():
    png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
    async with lifespan(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as admin:
        assert (await admin.post("/api/auth/login",json={"email":"admin@example.com","password":"test-password"})).status_code==200
        team=(await admin.post("/api/teams",json={"name":"Logo FC"})).json()
        assert team["has_logo"] is False and "logo_path" not in team  # filesystem path stays private
        assert (await admin.post(f"/api/teams/{team['id']}/logo",files={"file":("l.txt",b"not an image","text/plain")})).status_code==400
        assert (await admin.post(f"/api/teams/{team['id']}/logo",files={"file":("l.png",b"","image/png")})).status_code==400
        assert (await admin.post(f"/api/teams/{team['id']}/logo",files={"file":("l.png",b"x"*2_000_001,"image/png")})).status_code==413
        assert (await admin.get(f"/api/teams/{team['id']}/logo")).status_code==404
        up=await admin.post(f"/api/teams/{team['id']}/logo",files={"file":("logo.png",png,"image/png")})
        assert up.status_code==200 and up.json()["has_logo"] is True
        assert any(t["id"]==team["id"] and t["has_logo"] for t in (await admin.get("/api/teams")).json())
        got=await admin.get(f"/api/teams/{team['id']}/logo")
        assert got.status_code==200 and got.headers["content-type"]=="image/png" and got.content==png
        logo_png=TEST_ROOT/"storage"/"logos"/f"{team['id']}.png";assert logo_png.is_file()
        # replacing with a jpeg removes the previous file (extension can change)
        up2=await admin.post(f"/api/teams/{team['id']}/logo",files={"file":("l.jpg",b"\xff\xd8\xff\xe0fakejpeg","image/jpeg")})
        assert up2.status_code==200 and not logo_png.exists()
        got2=await admin.get(f"/api/teams/{team['id']}/logo")
        assert got2.status_code==200 and got2.headers["content-type"]=="image/jpeg"
        assert (await admin.delete(f"/api/teams/{team['id']}/logo")).status_code==204
        assert (await admin.get(f"/api/teams/{team['id']}/logo")).status_code==404
        assert not (TEST_ROOT/"storage"/"logos"/f"{team['id']}.jpg").exists()
        # team delete cleans the logo file too
        await admin.post(f"/api/teams/{team['id']}/logo",files={"file":("logo.png",png,"image/png")})
        assert (await admin.delete(f"/api/teams/{team['id']}")).status_code==204
        assert not (TEST_ROOT/"storage"/"logos"/f"{team['id']}.png").exists()


async def event_window_export(tmp_path):
    from app.media import probe
    media=tmp_path/"window.mp4"
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=c=green:s=640x360:r=25",
                    "-t","6","-c:v","libx264","-threads","2","-pix_fmt","yuv420p",str(media)],check=True,capture_output=True)
    async with lifespan(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as c:
        assert (await c.post('/api/auth/login',json={"email":"admin@example.com","password":"test-password"})).status_code==200
        match=(await c.post('/api/matches',json={"date":"2026-10-04","home_team":"Window test","away_team":"Fixture"})).json()
        video=(await c.post(f"/api/matches/{match['id']}/videos",files={"file":("window.mp4",media.read_bytes(),"video/mp4")})).json()
        for _ in range(150):
            state=(await c.get(f"/api/matches/{match['id']}")).json()['videos'][0]
            if state['status'] in ('ready','failed'):break
            await asyncio.sleep(.1)
        assert state['status']=='ready',state
        category=(await c.get('/api/categories')).json()[0]
        event=(await c.post(f"/api/matches/{match['id']}/events",json={"video_id":video['id'],"category_id":category['id'],"timestamp":3,"start":1,"end":5})).json()
        assert event['start']==1 and event['end']==5
        patched=await c.patch(f"/api/events/{event['id']}",json={"start":1,"end":2.5})
        assert patched.status_code==200,patched.text
        assert patched.json()['start']==1 and patched.json()['end']==2.5
        assert (await c.patch(f"/api/events/{event['id']}",json={"start":3,"end":2})).status_code==400
        assert (await c.patch(f"/api/events/{event['id']}",json={"start":-1})).status_code==422
        assert (await c.post(f"/api/matches/{match['id']}/events",json={"video_id":video['id'],"category_id":category['id'],"timestamp":4,"start":5,"end":4})).status_code==400
        # Even when the client sends wider fixed seconds, an event clip covers the event window.
        job=(await c.post('/api/exports/clip',json={"video_id":video['id'],"event_id":event['id'],"start":0,"end":6,"overlay":None,"include_annotations":False,"freeze_seconds":0})).json()
        for _ in range(150):
            job_state=(await c.get(f"/api/jobs/{job['id']}")).json()
            if job_state['status'] in ('completed','failed'):break
            await asyncio.sleep(.1)
        assert job_state['status']=='completed',job_state
        output=tmp_path/'window-export.mp4';output.write_bytes((await c.get(f"/api/jobs/{job['id']}/download")).content)
        assert abs(float(probe(output)['format']['duration'])-1.5)<.3
