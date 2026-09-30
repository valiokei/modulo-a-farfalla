import logging
import os
import queue
import threading
import uuid
from pathlib import Path
from sqlalchemy import select
from .db import SessionLocal
from .models import AIJob, AISuggestion, Annotation, Event, Job, JobStatus, Video
from .media import encode_h264, make_proxy, run_ffmpeg, safe_path
from .config import settings
from .telestration import annotation_freeze, annotation_layers


logger = logging.getLogger(__name__)
_jobs: queue.Queue[tuple] = queue.Queue(maxsize=64)


def _esc_drawtext(value: str) -> str:
    """Escape a drawtext string for the FFmpeg drawtext filter."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def _overlay_filter(overlay: dict | str | None):
    """Build the bottom-band overlay filter. Returns None when no overlay is requested."""
    if not overlay:
        return None
    if isinstance(overlay, str):
        blocks=[str(overlay)]
        pitch=None
    else:
        header=overlay.get("header") or ""
        minute=overlay.get("minute") or ""
        team=overlay.get("team") or ""
        player=overlay.get("player") or ""
        note=overlay.get("note") or ""
        blocks=[]
        if header: blocks.append(header)
        if minute:
            if blocks: blocks[-1] = f"{blocks[-1]}  •  {minute}"
            else: blocks.append(minute)
        detail=" • ".join([part for part in [team,player,note] if part])
        if detail: blocks.append(detail)
        pitch_x=overlay.get("pitch_x"); pitch_y=overlay.get("pitch_y")
        pitch=(pitch_x,pitch_y) if pitch_x is not None and pitch_y is not None else None
    if not blocks and pitch is None:
        return None
    # A block text containing a comma would be interpreted as an option separator;
    # sanitize commas to middot to keep drawtext parsing safe.
    blocks=[b.replace(",", "•") for b in blocks]
    filter_parts=["drawbox=x=0:y=ih-100:w=iw:h=100:color=black@0.6:t=fill"]
    for idx, block in enumerate(blocks):
        if block:
            esc=str(block)[:180].replace(chr(39), "").replace('\\', '\\\\').replace(':', '\\:').replace('%', '\\%')
            filter_parts.append(f"drawtext=text='{esc}':x=24:y=h-{int(88-idx*26)}:fontsize=24:fontcolor=white")
    if pitch is not None:
        px = float(pitch[0]) if pitch and len(pitch) > 0 else 0.5
        py = float(pitch[1]) if pitch and len(pitch) > 1 else 0.5
        pw, ph = 72, 44
        dx = round(px*pw)
        dy = round(py*ph)
        filter_parts.append(f"drawbox=x=iw-110:y=h-84:w={pw}:h={ph}:color=#2e7d3b@0.85:t=fill")
        filter_parts.append(f"drawbox=x=iw-74:y=h-84:w=2:h={ph}:color=white@0.8:t=fill")
        filter_parts.append(f"drawbox=x=iw-110:y=h-62:w={pw}:h=2:color=white@0.8:t=fill")
        filter_parts.append(f"drawbox=x=iw-110+{dx}-3:y=h-84+{dy}-3:w=6:h=6:color=yellow@0.95:t=fill")
    return ",".join(filter_parts)


def _job_worker() -> None:
    while True:
        target, args = _jobs.get()
        try:
            target(*args)
        except Exception:
            logger.exception("Background job failed")
        finally:
            _jobs.task_done()


for worker_no in range(max(1, settings.background_workers)):
    threading.Thread(target=_job_worker, name=f"touchline-worker-{worker_no + 1}", daemon=True).start()


def launch(target, *args) -> None:
    try:
        _jobs.put_nowait((target, args))
    except queue.Full as exc:
        raise RuntimeError("Background queue is full; retry shortly") from exc


def transcode(video_id: str) -> None:
    with SessionLocal() as db:
        video = db.get(Video, video_id)
        if not video: return
        automatic_ai_job_id = None
        video.status = "processing";video.processing_progress=1;video.error=None;db.commit();last_saved=1
        def save_progress(value:int) -> None:
            nonlocal last_saved
            value=max(1,min(100,int(value)))
            if value<100 and value-last_saved<2:return
            video.processing_progress=value;db.commit();last_saved=value
        try:
            proxy = safe_path("proxies", f"{video.id}.mp4")
            thumb = safe_path("thumbnails", f"{video.id}.jpg")
            video.duration = make_proxy(Path(video.original_path),proxy,thumb,save_progress)
            video.proxy_path=str(proxy);video.thumbnail_path=str(thumb);video.processing_progress=100;video.status="ready"
        except Exception as exc:
            video.status = "failed"; video.error = str(exc)
        if video.status=="ready" and video.analyze_after_processing:
            ai_job=AIJob(video_id=video.id,config={"source":"automatic-import"});db.add(ai_job);db.flush();automatic_ai_job_id=ai_job.id
        db.commit()
        if automatic_ai_job_id:launch(analyze,automatic_ai_job_id)


def export_clip(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job: return
        job.status = JobStatus.running; job.progress = 10; db.commit()
        try:
            p = job.payload; video = db.get(Video, p["video_id"])
            if not video or video.status != "ready": raise ValueError("Video is not ready")
            output = safe_path("clips" if job.kind == "clip" else "exports", f"{job.id}.mp4")
            source = video.proxy_path or video.original_path
            event = db.get(Event, p.get("event_id")) if p.get("event_id") else None
            offset = (video.time_offset or 0) if event else 0
            start, end = max(0, float(p["start"]) - offset), min(video.duration, float(p["end"]) - offset)
            if end <= start: raise ValueError("Invalid clip range")
            video_filter = _overlay_filter(p.get("overlay", "") or None)
            annotation = latest_annotation(db, event.id) if event and p.get("include_annotations", True) else None
            freeze = annotation_freeze(annotation, source, start, end, p.get("freeze_seconds", 0), offset)
            with annotation_layers(annotation, event, source, start, end, output, time_offset=offset, freeze=freeze) as layers:
                encode_h264(source,output,start=start,end=end,filters=video_filter,overlays=layers,freeze=freeze,hardware_decode=not video_filter or os.name == "nt")
            job.result = {"path": str(output), "download": f"/api/jobs/{job.id}/download"}; job.progress = 100; job.status = JobStatus.completed
        except Exception as exc:
            job.status = JobStatus.failed; job.error = str(exc)
        db.commit()


def latest_annotation(db, event_id):
    return db.scalar(select(Annotation).where(Annotation.event_id == event_id).order_by(Annotation.created_at.desc(), Annotation.id.desc()).limit(1))


def export_highlight(job_id: str) -> None:
    with SessionLocal() as db:
        job=db.get(Job,job_id)
        if not job:return
        job.status=JobStatus.running;db.commit();parts=[];manifest=None
        try:
            ids=job.payload.get("event_ids",[])
            events=[db.get(Event,event_id) for event_id in ids]
            events=[e for e in events if e]
            if not events:raise ValueError("Playlist has no valid events")
            for i,event in enumerate(events):
                video=db.get(Video,event.video_id)
                if not video or video.status!="ready":raise ValueError("A playlist video is not ready")
                output=safe_path("exports",f"{job.id}-part-{i}.mp4");parts.append(output)
                offset=video.time_offset or 0
                start=max(0,(event.start if event.start is not None else event.timestamp-5)-offset);end=min(video.duration,(event.end if event.end is not None else event.timestamp+5)-offset)
                overlay_d = None
                if job.payload.get("overlay"):
                    cat=event.category.name if event.category else ""
                    actor=""
                    if event.event_players:
                        try: actor=event.event_players[0].player.name or ""
                        except Exception: pass
                    team=event.team or ""
                    overlay_d={"header":cat,"minute":f"{int(event.timestamp//60)}'", "team":team,"player":actor,"note":event.note,"pitch_x":event.pitch_x,"pitch_y":event.pitch_y}
                source = video.proxy_path or video.original_path
                annotation = latest_annotation(db, event.id) if job.payload.get("include_annotations", True) else None
                freeze=annotation_freeze(annotation,source,start,end,job.payload.get("freeze_seconds",0),offset)
                with annotation_layers(annotation, event, source, start, end, output, time_offset=offset, freeze=freeze) as layers:
                    encode_h264(source,output,start=start,end=end,filters=_overlay_filter(overlay_d),overlays=layers,freeze=freeze)
                job.progress=int(80*(i+1)/len(events));db.commit()
            manifest=safe_path("exports",f"{job.id}.txt")
            manifest.write_text("".join(f"file '{p.name}'\n" for p in parts),encoding="utf-8")
            final=safe_path("exports",f"{job.id}.mp4")
            run_ffmpeg(["-f","concat","-safe","1","-i",str(manifest),"-c","copy","-movflags","+faststart",str(final)])
            job.result={"path":str(final),"download":f"/api/jobs/{job.id}/download"};job.progress=100;job.status=JobStatus.completed
        except Exception as exc:
            job.status=JobStatus.failed;job.error=str(exc)
        finally:
            for part in parts:part.unlink(missing_ok=True)
            if manifest:manifest.unlink(missing_ok=True)
        db.commit()


def run_spotting_process(proxy: Path, work: Path, progress) -> None:
    import json
    import os
    import subprocess
    import sys
    import time
    environment = dict(os.environ, OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", OSL_PRETRAINED_WEIGHTS="0", WANDB_MODE="disabled", HF_HOME=str(settings.storage_root / "model-cache"))
    command = [settings.ai_python or sys.executable,"-m","app.spotting_cli",str(proxy.resolve()),str(work.resolve()),"--device",settings.ai_device,"--batch-size",str(settings.ai_batch_size)]
    with (work / "inference.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, env=environment)
        started = time.monotonic()
        while process.poll() is None:
            if time.monotonic()-started > 12*3600:
                process.kill(); process.wait()
                raise TimeoutError("Action spotting exceeded 12 hours")
            progress_path = work / "progress.json"
            if progress_path.exists():
                state = json.loads(progress_path.read_text())
                progress(min(95, state["progress"]), state["stage"])
            time.sleep(1)
        if process.returncode:
            raise RuntimeError("OpenSportsLib inference failed: " + (work / "inference.log").read_text()[-1200:])


def analyze(ai_job_id: str) -> None:
    """Run the official action model in a resource-limited subprocess."""
    import json
    from .action_spotting import CATEGORIES
    with SessionLocal() as db:
        job = db.get(AIJob, ai_job_id)
        if not job: return
        job.status = JobStatus.running; job.progress = 1; db.commit()
        try:
            video = db.get(Video, job.video_id)
            if not video or video.status != "ready":
                raise ValueError("Video must finish preparation before action spotting")
            work = settings.storage_root / "ai" / job.id
            work.mkdir(parents=True, exist_ok=True)
            proxy = settings.storage_root / "ai" / f"{video.id}-224p-v1.mp4"
            if not proxy.exists():
                partial = proxy.with_suffix(".partial.mp4")
                run_ffmpeg(["-i",video.proxy_path or video.original_path,"-an","-vf","scale=398:224","-r","25","-c:v","libx264","-preset","veryfast","-threads","2",str(partial)])
                partial.replace(proxy)
            def save_ai_progress(percent, stage):
                job.progress = percent
                job.config = {**job.config, "stage": stage}
                db.commit()
            run_spotting_process(proxy, work, save_ai_progress)
            result = json.loads((work / "suggestions.json").read_text())
            for prediction in result["predictions"]:
                timestamp = prediction["timestamp"]
                if not 0 <= timestamp <= video.duration: continue
                db.add(AISuggestion(ai_job_id=job.id,timestamp=timestamp,proposed_category=CATEGORIES[prediction["action"]],confidence=prediction["confidence"],evidence={**prediction,"context_start":max(0,timestamp-8),"context_end":min(video.duration,timestamp+8),"field_confidences":{"action":prediction["confidence"]},"tracking":None}))
            job.config = {**job.config, "stage":"Completed", "runtime":json.loads((work / "provenance.json").read_text()), "elapsed_seconds":result["elapsed_seconds"]}
            job.progress = 100; job.status = JobStatus.completed
        except Exception as exc:
            job.status = JobStatus.failed; job.error = str(exc)
            logger.exception("Action spotting failed for %s", ai_job_id)
        db.commit()
