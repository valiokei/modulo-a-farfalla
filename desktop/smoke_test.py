"""Exercise the actual packaged executable, not a mock server."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))


def wait_for(client, path, key, expected, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        value = response.json()
        if value[key] == expected:
            return value
        if value[key] == "failed":
            raise AssertionError(value.get("error", "Job failed"))
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve() if args.executable else None
    from desktop.launcher import load_config, configure_environment, migrate_database, initialize_local_user, atomic_json
    root = Path(tempfile.mkdtemp(prefix="modulo smoke "))
    config = load_config(root)
    configure_environment(root, config)
    migrate_database(root)
    local_email = initialize_local_user(config)
    config.update(initialized=True, analyst_email=local_email)
    atomic_json(root / "desktop.json", config)
    ready = root / "ready.json"
    command = [str(executable)] if executable else [sys.executable, str(ROOT / "desktop" / "launcher.py")]
    process = subprocess.Popen(command + ["--headless", "--data-dir", str(root), "--ready-file", str(ready)])
    try:
        deadline = time.monotonic() + 90
        while not ready.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError((root / "logs" / "desktop.log").read_text(encoding="utf-8"))
            time.sleep(0.2)
        assert ready.exists(), "No readiness signal"
        url = json.loads(ready.read_text(encoding="utf-8"))["url"]
        assert url.startswith("http://127.0.0.1:")
        with httpx.Client(base_url=url, timeout=60) as client:
            health = client.get("/desktop/health").json()
            assert health["workers"] == 1
            assert health["video"]["selected"] in {"cpu", "nvidia", "intel", "amd"}
            if os.name == "nt":
                assert len(health["video"]["encoders"]) == 3
            assert client.get("/desktop/health").json()["ai_bundled"] is False
            assert client.get("/desktop/update/status").status_code == 404
            # The SPA GET catch-all may return 405 for an unknown POST route.
            assert client.post("/desktop/update/credentials", json={"token": "not-a-real-token"}).status_code in {404, 405}
            page = client.get("/")
            assert page.status_code == 200 and 'id="root"' in page.text
            assert page.headers["X-Content-Type-Options"] == "nosniff"
            assert client.get("/api/teams").status_code == 200
            assert client.get("/api/auth/me").json()["role"] == "coach"
            assert client.get("/", headers={"Host": "evil.invalid"}).status_code == 400
            login = {"email": local_email, "password": "unused-local-login"}
            assert client.post("/api/auth/login", json=login, headers={"Origin": "https://evil.invalid"}).status_code == 403
            assert client.post("/api/auth/login", json=login).status_code == 404
            assert client.post("/api/ai/jobs", json={"video_id": "absent"}).status_code == 503
            match = client.post("/api/matches", json={"date": "2026-01-01", "home_team": "Local Home", "away_team": "Local Away"}).json()
            if executable:
                ffmpeg = executable.parent / "_internal" / "ffmpeg" / "ffmpeg.exe"
            else:
                ffmpeg = "ffmpeg"
            video = root / "sample.mp4"
            subprocess.run([str(ffmpeg), "-y", "-f", "lavfi", "-i", "color=c=green:s=320x180:r=25,drawbox=x=190:y=10:w=80:h=25:c=red:t=fill:enable='lt(t,0.8)'",
                            "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                           check=True, capture_output=True, timeout=30)
            upload = client.post(f"/api/matches/{match['id']}/videos", files={"file": ("sample.mp4", video.read_bytes(), "video/mp4")},
                                 data={"label": "Local", "time_offset": "0", "analyze_ai": "false"})
            upload.raise_for_status()
            video_id = upload.json()["id"]
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                state = client.get(f"/api/matches/{match['id']}").json()["videos"][0]
                if state["status"] in {"ready", "failed"}:
                    break
                time.sleep(0.2)
            assert state["status"] == "ready", state
            if os.name == "nt":
                last = client.get("/desktop/health").json()["video"]["last_operation"]
                assert last["encoder"] in {"cpu", "nvidia", "intel", "amd"}
                print("PASS: real Windows encoding backend:", last["encoder"])
            original = next((root / "storage" / "originals").iterdir())
            assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(video.read_bytes()).digest()
            stream = client.get(f"/api/videos/{video_id}/stream", headers={"Range": "bytes=0-99"})
            assert stream.status_code == 206 and len(stream.content) == 100
            category = client.get("/api/categories").json()[0]
            event = client.post(f"/api/matches/{match['id']}/events", json={"video_id": video_id, "category_id": category["id"], "timestamp": 0.5})
            event.raise_for_status()
            event_id = event.json()["id"]
            annotation = client.post(f"/api/events/{event_id}/annotations", json={
                "timestamp": .5, "start": 0, "end": 1, "coordinate_mode": "screen",
                "shapes": [{"type": "pen", "points": [[.2,y],[.8,y]], "color": "#ffdf36",
                            "lineWidth": 10, "start": 0, "end": 1} for y in (.25,.35)]})
            annotation.raise_for_status()
            export = client.post("/api/exports/clip", json={"video_id": video_id, "start": 0, "end": 1}).json()
            wait_for(client, f"/api/jobs/{export['id']}", "status", "completed")
            output = client.get(f"/api/jobs/{export['id']}/download")
            assert output.status_code == 200 and len(output.content) > 1000
            annotated = client.post("/api/exports/clip", json={
                "video_id": video_id, "event_id": event_id, "start": 0, "end": 2, "freeze_seconds": 2,
                "overlay": {"header": "Desktop test", "team": "Local", "pitch_x": 0.5, "pitch_y": 0.5}
            }).json()
            wait_for(client, f"/api/jobs/{annotated['id']}", "status", "completed")
            result = client.get(f"/api/jobs/{annotated['id']}/download")
            assert result.status_code == 200
            exported = root / "annotated.mp4"
            exported.write_bytes(result.content)
            import numpy as np
            pixels = subprocess.run([str(ffmpeg), "-v", "error", "-ss", "1", "-i", str(exported),
                                     "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                    check=True, capture_output=True, timeout=30)
            frame = np.frombuffer(pixels.stdout, dtype=np.uint8).reshape(180,320,3)
            for y in (45,63):
                strip = frame[y-2:y+3,80:240]
                yellow = (strip[:,:,0]>180)&(strip[:,:,1]>160)&(strip[:,:,2]<120)
                assert yellow.sum()>150, "Saved pencil stroke missing from actual exported video"
            print("PASS: actual exported pixels contain both saved yellow strokes")
            def read_frame(path, instant):
                data=subprocess.run([str(ffmpeg),'-v','error','-ss',str(instant),'-i',str(path),
                    '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True,timeout=30).stdout
                return np.frombuffer(data,dtype=np.uint8).reshape(180,320,3).astype(float)
            assert np.abs(read_frame(video,.5)-read_frame(video,1)).mean()>2
            assert np.abs(read_frame(exported,1)-read_frame(exported,2)).mean()<1
            # This source box disappears at .8s; with a 2s hold it disappears at 2.8s.
            assert read_frame(exported,2)[15:25,200:260,0].mean()>150
            assert read_frame(exported,3)[15:25,200:260,0].mean()<100
            ffprobe = executable.parent/'_internal'/'ffmpeg'/'ffprobe.exe' if executable else 'ffprobe'
            duration=subprocess.run([str(ffprobe),'-v','error','-show_entries','format=duration',
                '-of','default=nw=1:nk=1',str(exported)],capture_output=True,text=True,check=True,timeout=30).stdout
            assert abs(float(duration)-4)<.15
            print('PASS: installed export freezes the saved frame for 2s then resumes, without altering originals')

        with sqlite3.connect(root / "touchline.db") as database:
            assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert database.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0006"
        assert list((root / "database-backups").glob("*.db")), "No verified pre-migration backup"
        print("PASS: packaged local server, authentication, Host/Origin protection, upload, proxy, range streaming, tagging, export, SQLite migration and backup")
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
