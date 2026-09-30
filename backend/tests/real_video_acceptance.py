"""Explicit slow acceptance: REAL_VIDEO=/path/clip.mp4 AI_PYTHON=/path/python python -m tests.real_video_acceptance.

Creates a temporary isolated database; uses actual official inference, not mocked results.
"""
import asyncio
import json
import os
from pathlib import Path
import tempfile

root=Path(tempfile.mkdtemp(prefix="touchline-real-ai-"))
os.environ["DATABASE_URL"]=f"sqlite:///{root/'acceptance.db'}"
os.environ["STORAGE_ROOT"]=str(root/'storage')
os.environ["BOOTSTRAP_ADMIN_PASSWORD"]="acceptance-only"
os.environ["MEDIA_ACCELERATION"]="cpu"
import httpx
from app.main import app, lifespan


async def main():
    video=Path(os.environ["REAL_VIDEO"])
    async with lifespan(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        response=await client.post('/api/auth/login',json={"email":"admin@example.com","password":"acceptance-only"});response.raise_for_status()
        match=(await client.post('/api/matches',json={"date":"2026-09-17","home_team":"Acceptance home","away_team":"Acceptance away"})).json()
        response=await client.post(f"/api/matches/{match['id']}/videos",files={"file":(video.name,video.read_bytes(),"video/mp4")},data={"analyze_ai":"true"});response.raise_for_status()
        uploaded=response.json()
        for _ in range(300):
            response=await client.get(f"/api/videos/{uploaded['id']}/ai-job")
            if response.status_code==200:
                job=response.json()
                if job['status'] in ('failed','completed'):break
            await asyncio.sleep(1)
        assert job['status']=='completed',job
        assert job['suggestions'],"Real inference returned no candidates; inspect raw predictions, do not fabricate events."
        suggestion=job['suggestions'][0]
        assert suggestion['evidence']['source']=='NEURAL_MODEL'
        assert (await client.get(f"/api/videos/{uploaded['id']}/stream",headers={"Range":"bytes=0-99"})).status_code==206
        category=next(c for c in (await client.get('/api/categories')).json() if c['name']=='Cross')
        assert (await client.post(f"/api/ai/suggestions/{suggestion['id']}",json={"action":"edit","category_id":category['id'],"note":"Human correction acceptance test"})).status_code==200
        accepted=await client.post(f"/api/ai/suggestions/{suggestion['id']}",json={"action":"accept"});accepted.raise_for_status()
        events=(await client.get(f"/api/matches/{match['id']}/events")).json()
        assert len(events)==1 and events[0]['category']['name']=='Cross' and events[0]['note']=='Human correction acceptance test'
        if len(job['suggestions'])>1:
            rejected=await client.post(f"/api/ai/suggestions/{job['suggestions'][1]['id']}",json={"action":"reject"});assert rejected.json()['status']=='rejected'
        print(json.dumps({"database":str(root/'acceptance.db'),"suggestions":len(job['suggestions']),"runtime":job['config'],"review":"edit/accept/reject persisted"},indent=2))


if __name__=='__main__':asyncio.run(main())
