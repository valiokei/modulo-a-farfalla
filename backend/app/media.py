import json
import logging
import os
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from fastapi import HTTPException
from .config import settings


KINDS = ("originals", "proxies", "thumbnails", "clips", "exports", "logos")
logger = logging.getLogger(__name__)


def initialize_storage() -> None:
    for kind in KINDS:
        (settings.storage_root / kind).mkdir(parents=True, exist_ok=True)


def safe_path(kind: str, name: str) -> Path:
    if kind not in KINDS or Path(name).name != name:
        raise HTTPException(400, "Invalid storage path")
    return settings.storage_root / kind / name


def probe(path: Path) -> dict:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height:stream_side_data=rotation", "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    if proc.returncode:
        raise ValueError(proc.stderr[-500:] or "ffprobe failed")
    data = json.loads(proc.stdout)
    if not any(x.get("codec_type") == "video" for x in data.get("streams", [])):
        raise ValueError("File has no video stream")
    return data


def _low_priority() -> None:
    try: os.nice(max(0, settings.worker_nice))
    except OSError: pass


def subprocess_options() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS}
    return {"preexec_fn": _low_priority}


def run_ffmpeg(args: list[str], timeout: int = 12 * 3600, progress_duration: float | None = None, progress_callback=None) -> None:
    command=["ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y"]
    if progress_duration and progress_callback:command += ["-progress","pipe:1","-nostats"]
    if not progress_duration or not progress_callback:
        proc=subprocess.run([*command,*args],capture_output=True,text=True,timeout=timeout,**subprocess_options())
        if proc.returncode:raise RuntimeError(proc.stderr[-1000:] or "FFmpeg failed")
        return
    proc=subprocess.Popen([*command,*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,**subprocess_options())
    started=time.monotonic();last_percent=-1
    assert proc.stdout is not None
    for line in proc.stdout:
        if time.monotonic()-started>timeout:
            proc.kill();raise TimeoutError("FFmpeg timed out")
        key,_,value=line.strip().partition("=")
        if key=="out_time_us" and value.isdigit():
            percent=min(97,max(1,int((int(value)/1_000_000)/progress_duration*97)))
            if percent!=last_percent:progress_callback(percent);last_percent=percent
    stderr=proc.stderr.read() if proc.stderr else "";return_code=proc.wait()
    if return_code:raise RuntimeError(stderr[-1000:] or "FFmpeg failed")


@lru_cache(maxsize=1)
def vaapi_available() -> bool:
    if settings.media_acceleration.lower() not in {"auto", "vaapi"} or not settings.vaapi_device.exists(): return False
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15, **subprocess_options())
    return proc.returncode == 0 and "h264_vaapi" in proc.stdout


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    if settings.media_acceleration.lower() not in {"auto", "nvidia", "nvenc"}:
        return False
    check = subprocess.run(["ffmpeg", "-hide_banner", "-encoders", "nvidia"], capture_output=True, text=True, timeout=15, **subprocess_options())
    has_encoder = "h264_nvenc" in check.stdout
    device = Path(settings.nvenc_device)
    if settings.nvidia_visible_devices.strip() not in ("", "all") and not device.exists():
        return False
    return has_encoder


@lru_cache(maxsize=1)
def hardware_backend() -> str:
    forced = settings.force_hardware.strip().lower()
    if os.name == "nt":
        from .windows_gpu import candidates
        choices = candidates(forced or settings.media_acceleration)
        return choices[0].vendor if choices else "cpu"
    if forced == "nvidia" and nvenc_available():
        return "nvidia"
    if forced == "amdx" and vaapi_available():
        return "vaapi"
    if forced == "cpu":
        return "cpu"
    if nvenc_available():
        return "nvidia"
    if vaapi_available():
        return "vaapi"
    return "cpu"


def video_filter_args(filters=None, overlays=(), suffix=None, freeze=None) -> list[str]:
    chain = ",".join(part for part in (filters, suffix) if part)
    if not overlays and not freeze:
        return ["-map", "0:v:0", "-map", "0:a?", *(["-vf", chain] if chain else [])]
    inputs = [arg for path, _, _ in overlays for arg in ("-i", str(path))]
    graph = ["[0:v:0]setpts=PTS-STARTPTS[base]"]
    audio = "0:a?"
    if freeze:
        at, duration, has_audio = freeze
        # Insert, rather than replace, the paused frame. Audio resumes at the
        # same source instant after an equally long silent interval.
        branches = 3 if at > 0 else 2
        graph = [f"[0:v:0]setpts=PTS-STARTPTS,split={branches}" + ("[pre]" if at > 0 else "") + "[still][post]"]
        if at > 0: graph.append(f"[pre]trim=end={at:.6f},setpts=PTS-STARTPTS[before]")
        graph += [f"[still]trim=start={at:.6f},trim=end_frame=1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={duration:.6f},trim=duration={duration:.6f}[hold]",
                  f"[post]trim=start={at:.6f},setpts=PTS-STARTPTS[after]",
                  ("[before]" if at > 0 else "") + f"[hold][after]concat=n={branches}:v=1:a=0[base]"]
        if has_audio:
            graph += ["[0:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS" + (",asplit=2[apre][apost]" if at > 0 else "[apost]"),
                      f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.6f}[silence]",
                      f"[apost]atrim=start={at:.6f},asetpts=PTS-STARTPTS[aafter]"]
            if at > 0: graph.append(f"[apre]atrim=end={at:.6f},asetpts=PTS-STARTPTS[abefore]")
            graph.append(("[abefore]" if at > 0 else "") + f"[silence][aafter]concat=n={branches}:v=0:a=1[pausedaudio]")
            audio = "[pausedaudio]"
    previous = "base"
    for i, (_, first, last) in enumerate(overlays, 1):
        graph.append(f"[{previous}][{i}:v:0]overlay=0:0:eof_action=repeat:enable='gte(t,{first:.6f})*lt(t,{last:.6f})'[ink{i}]")
        previous = f"ink{i}"
    graph.append(f"[{previous}]{chain or 'null'}[composed]")
    return [*inputs, "-filter_complex_threads", str(max(1, settings.ffmpeg_threads)),
            "-filter_complex", ";".join(graph), "-map", "[composed]", "-map", audio]


def encode_h264(source: Path | str, output: Path, *, start: float | None = None, end: float | None = None, filters: str | None = None, overlays=(), freeze=None, hardware_decode: bool = True, progress_duration: float | None = None, progress_callback=None) -> None:
    seek = []
    if start is not None: seek += ["-ss", str(start)]
    if end is not None: seek += ["-to", str(end)]
    windows_fallback = False
    if os.name == "nt":
        from .windows_gpu import try_encode
        if try_encode(source, output, seek=seek, filters=filters, hardware_decode=hardware_decode,
                      preference=settings.force_hardware or settings.media_acceleration, run=run_ffmpeg,
                      progress_duration=progress_duration, progress_callback=progress_callback, overlays=overlays, freeze=freeze):
            return
        windows_fallback = True
    backend = "cpu" if windows_fallback else hardware_backend()
    if backend == "nvidia":
        try:
            pre = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if hardware_decode and not filters and not overlays and not freeze else []
            suffix = "format=yuv420p,hwupload_cuda" if filters or overlays or freeze else "scale_cuda=format=yuv420p" if hardware_decode else None
            args = [*seek, *pre, "-i", str(source), *video_filter_args(filters, overlays, suffix, freeze)]
            run_ffmpeg([*args, "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", "-c:a", "aac", "-movflags", "+faststart", str(output)],progress_duration=progress_duration,progress_callback=progress_callback)
            return
        except Exception as exc:
            logger.warning("NVENC encode failed; using limited CPU fallback: %s", exc)
            output.unlink(missing_ok=True)
    elif backend == "vaapi":
        try:
            device = str(settings.vaapi_device)
            if hardware_decode and not filters and not overlays and not freeze:
                args = [*seek, "-hwaccel", "vaapi", "-hwaccel_device", device, "-hwaccel_output_format", "vaapi", "-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-vf", "scale_vaapi=format=nv12"]
            else:
                args = [*seek, "-vaapi_device", device, "-i", str(source), *video_filter_args(filters, overlays, "format=nv12,hwupload", freeze)]
            run_ffmpeg([*args, "-c:v", "h264_vaapi", "-qp", "24", "-profile:v", "high", "-c:a", "aac", "-movflags", "+faststart", str(output)],progress_duration=progress_duration,progress_callback=progress_callback)
            return
        except Exception as exc:
            logger.warning("VA-API encode failed; using limited CPU fallback: %s", exc)
            output.unlink(missing_ok=True)
    run_ffmpeg([*seek, "-i", str(source), *video_filter_args(filters, overlays, freeze=freeze), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-threads", str(max(1, settings.ffmpeg_threads)), "-c:a", "aac", "-movflags", "+faststart", str(output)],progress_duration=progress_duration,progress_callback=progress_callback)

    if windows_fallback:
        from .windows_gpu import record_operation
        record_operation("cpu", "software", fallback=True, filters=bool(filters or overlays))
        logger.info("Windows encode completed using limited CPU fallback")


def make_proxy(original: Path, proxy: Path, thumbnail: Path, progress_callback=None) -> float:
    info = probe(original)
    duration = float(info["format"].get("duration", 0))
    if progress_callback:progress_callback(1)
    encode_h264(original,proxy,progress_duration=duration,progress_callback=progress_callback)
    if progress_callback:progress_callback(98)
    run_ffmpeg(["-threads", str(max(1, settings.ffmpeg_threads)), "-ss", str(min(1, duration / 2)), "-i", str(original), "-frames:v", "1", "-vf", "scale=480:-2", str(thumbnail)])
    if progress_callback:progress_callback(100)
    return duration


def remove_video_files(*paths: str | None) -> None:
    for value in paths:
        if value:
            Path(value).unlink(missing_ok=True)


def disk_has_space(expected: int) -> bool:
    return shutil.disk_usage(settings.storage_root).free > max(expected * 2, 256 * 1024 * 1024)
