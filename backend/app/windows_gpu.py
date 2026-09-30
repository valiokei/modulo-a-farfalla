"""Windows H.264 acceleration: bounded real probes, never encoder-list guesses."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Encoder:
    vendor: str
    codec: str
    options: tuple[str, ...]
    initialization: tuple[str, ...] = ()


ENCODERS = (
    Encoder("nvidia", "h264_nvenc", ("-preset", "p4", "-rc", "vbr", "-b:v", "0", "-cq", "23", "-profile:v", "high")),
    Encoder("intel", "h264_qsv", ("-preset", "medium", "-b:v", "0", "-global_quality", "23", "-profile:v", "high"),
            ("-init_hw_device", "qsv=encode:hw,child_device_type=d3d11va")),
    Encoder("amd", "h264_amf", ("-quality", "balanced", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23", "-profile:v", "high")),
)
_lock = threading.Lock()
_probe_lock = threading.Lock()
_last_operation: dict = {}


def _process_options() -> dict:
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)}


@lru_cache(maxsize=1)
def discover_encoders() -> tuple[dict, ...]:
    # lru_cache alone can run the same expensive probe concurrently.
    with _probe_lock:
        return _discover_once()


@lru_cache(maxsize=1)
def _discover_once() -> tuple[dict, ...]:
    results = []
    for encoder in ENCODERS:
        try:
            # A compiled encoder is not evidence that a GPU/driver is usable.
            result = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                 *encoder.initialization, "-f", "lavfi", "-i", "color=c=black:s=128x128:r=30",
                 "-frames:v", "2", "-an", "-vf", "format=nv12",
                 "-c:v", encoder.codec, *encoder.options, "-f", "null", "-"],
                capture_output=True, timeout=8, **_process_options())
            available = result.returncode == 0
            reason = "ready" if available else "driver_or_encoder_unavailable"
        except subprocess.TimeoutExpired:
            available, reason = False, "probe_timeout"
        except OSError:
            available, reason = False, "ffmpeg_unavailable"
        results.append({"vendor": encoder.vendor, "encoder": encoder.codec,
                        "available": available, "reason": reason})
    logger.info("Windows video encoder probes: %s", results)
    return tuple(results)


def candidates(preference: str = "auto") -> tuple[Encoder, ...]:
    aliases = {"nvenc": "nvidia", "qsv": "intel", "amf": "amd"}
    preference = aliases.get(preference.lower(), preference.lower())
    if preference == "cpu":
        return ()
    available = {item["vendor"] for item in discover_encoders() if item["available"]}
    return tuple(item for item in ENCODERS if item.vendor in available
                 and (preference in {"", "auto"} or item.vendor == preference))


def status(preference: str = "auto") -> dict:
    options = candidates(preference)
    with _lock:
        last = dict(_last_operation)
    return {"selected": options[0].vendor if options else "cpu",
            "encoders": list(discover_encoders()), "last_operation": last,
            "decode_api": "d3d11va", "playback": "browser_managed"}


def record_operation(encoder: str, decoder: str, *, fallback: bool, filters: bool) -> None:
    with _lock:
        _last_operation.clear()
        _last_operation.update(encoder=encoder, decoder=decoder, fallback=fallback,
                               software_filters=filters, completed_at=time.time())


def try_encode(source: Path | str, output: Path, *, seek: list[str],
               filters: str | None, hardware_decode: bool, preference: str,
               run: Callable, progress_duration: float | None, progress_callback, overlays=(), freeze=None) -> bool:
    from .media import video_filter_args
    failed = False
    for encoder in candidates(preference):
        # D3D11VA decodes on all three vendors. Software frames keep the common
        # overlay pipeline compatible; upload/download and filters can use CPU.
        for decode in ([True, False] if hardware_decode else [False]):
            args = [*encoder.initialization, *seek, *(["-hwaccel", "d3d11va"] if decode else []),
                    "-i", str(source), *video_filter_args(filters, overlays, "format=nv12", freeze),
                    "-c:v", encoder.codec, *encoder.options, "-c:a", "aac",
                    "-movflags", "+faststart", str(output)]
            try:
                run(args, progress_duration=progress_duration, progress_callback=progress_callback)
                record_operation(encoder.vendor,
                                 "d3d11va_requested" if decode else "software",
                                 fallback=failed, filters=bool(filters or overlays))
                logger.info("Windows encode completed: vendor=%s hardware_decode_requested=%s software_filters=%s",
                            encoder.vendor, decode, bool(filters))
                return True
            except (RuntimeError, OSError, subprocess.SubprocessError, TimeoutError) as exc:
                failed = True
                output.unlink(missing_ok=True)
                # Do not leak paths, video titles or driver diagnostics into health.
                logger.warning("Windows %s encode attempt failed (%s); retrying safely",
                               encoder.vendor, type(exc).__name__)
    return False
