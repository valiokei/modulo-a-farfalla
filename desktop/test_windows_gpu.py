"""GPU paths use mocks; no real GPU or server is required by unit tests."""
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import media, windows_gpu as gpu


@pytest.fixture(autouse=True)
def reset_cache():
    gpu.discover_encoders.cache_clear()
    gpu._discover_once.cache_clear()
    media.hardware_backend.cache_clear()
    with gpu._lock:
        gpu._last_operation.clear()
    yield
    gpu.discover_encoders.cache_clear()
    gpu._discover_once.cache_clear()
    media.hardware_backend.cache_clear()


@pytest.mark.parametrize("vendor", ["nvidia", "intel", "amd"])
def test_probe_requires_real_success(monkeypatch, vendor):
    calls = []

    def probe(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 8
        assert "-encoders" not in command
        codec = command[command.index("-c:v") + 1]
        return SimpleNamespace(returncode=0 if codec == next(e.codec for e in gpu.ENCODERS if e.vendor == vendor) else 1)

    monkeypatch.setattr(gpu.subprocess, "run", probe)
    assert [e.vendor for e in gpu.candidates()] == [vendor]
    assert gpu.status()["selected"] == vendor
    gpu.candidates()
    assert len(calls) == 3


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("ffmpeg", 8)])
def test_probe_failure_is_bounded_and_cpu(monkeypatch, error):
    def failed(*args, **kwargs):
        raise error
    monkeypatch.setattr(gpu.subprocess, "run", failed)
    assert gpu.candidates() == ()
    assert gpu.status()["selected"] == "cpu"
    assert not any(item["available"] for item in gpu.discover_encoders())


@pytest.mark.parametrize("vendor", ["nvidia", "intel", "amd"])
@pytest.mark.parametrize("filters", [None, "drawbox=x=10:y=10:w=20:h=20"])
def test_each_vendor_export_and_transcode(monkeypatch, tmp_path, vendor, filters):
    encoder = next(e for e in gpu.ENCODERS if e.vendor == vendor)
    monkeypatch.setattr(gpu, "candidates", lambda _: (encoder,))
    calls = []
    output = tmp_path / "output.mp4"
    def run(command, **kwargs):
        calls.append(command)
        output.write_bytes(b"encoded")
    assert gpu.try_encode("original.mp4", output, seek=["-ss", "1", "-to", "2"],
                          filters=filters, hardware_decode=True, preference="auto",
                          run=run, progress_duration=1, progress_callback=None)
    command = calls[0]
    assert command[len(encoder.initialization):len(encoder.initialization) + 4] == ["-ss", "1", "-to", "2"]
    if vendor == "intel":
        assert "qsv=encode:hw,child_device_type=d3d11va" in command
    assert command[command.index("-hwaccel") + 1] == "d3d11va"
    assert command[command.index("-c:v") + 1] == encoder.codec
    assert command[command.index("-vf") + 1].endswith("format=nv12")
    with gpu._lock:
        assert gpu._last_operation["encoder"] == vendor
        assert gpu._last_operation["decoder"] == "d3d11va_requested"
        assert gpu._last_operation["software_filters"] == bool(filters)


def test_decoder_fallback_keeps_gpu_encoder(monkeypatch, tmp_path):
    monkeypatch.setattr(gpu, "candidates", lambda _: (gpu.ENCODERS[1],))
    output = tmp_path / "clip.mp4"
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if "-hwaccel" in command:
            output.write_bytes(b"partial")
            raise RuntimeError("Unsupported input codec")
        assert not output.exists()
        output.write_bytes(b"good")
    assert gpu.try_encode("input.mp4", output, seek=[], filters=None,
                          hardware_decode=True, preference="auto", run=run,
                          progress_duration=None, progress_callback=None)
    assert len(calls) == 2
    assert gpu._last_operation["encoder"] == "intel"
    assert gpu._last_operation["decoder"] == "software"
    assert gpu._last_operation["fallback"]


def test_next_vendor_after_runtime_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(gpu, "candidates", lambda _: gpu.ENCODERS)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if "h264_amf" not in command:
            raise RuntimeError("Device lost")
    assert gpu.try_encode("input.mp4", tmp_path / "out.mp4", seek=[], filters=None,
                          hardware_decode=True, preference="auto", run=run,
                          progress_duration=None, progress_callback=None)
    assert len(calls) == 5
    assert gpu._last_operation["encoder"] == "amd"


def test_all_gpu_failures_have_real_cpu_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(gpu, "candidates", lambda _: gpu.ENCODERS)
    monkeypatch.setattr(media.os, "name", "nt")
    calls = []
    output = tmp_path / "out.mp4"
    def run(command, **kwargs):
        calls.append(command)
        if "libx264" not in command:
            output.write_bytes(b"partial")
            raise RuntimeError("GPU error")
        assert not output.exists()
        assert command[command.index("-threads") + 1] == "2"
        output.write_bytes(b"CPU output")
    monkeypatch.setattr(media, "run_ffmpeg", run)
    media.encode_h264("original.mp4", output)
    assert len(calls) == 7
    assert gpu._last_operation["encoder"] == "cpu"
    assert gpu._last_operation["fallback"]


def test_failed_cpu_does_not_report_success(monkeypatch, tmp_path):
    monkeypatch.setattr(gpu, "candidates", lambda _: ())
    monkeypatch.setattr(media.os, "name", "nt")
    def run(*args, **kwargs):
        raise RuntimeError("Disk full")
    monkeypatch.setattr(media, "run_ffmpeg", run)
    with pytest.raises(RuntimeError, match="Disk full"):
        media.encode_h264("original.mp4", tmp_path / "out.mp4")
    assert not gpu._last_operation


def test_cpu_preference_never_probes(monkeypatch):
    def unexpected():
        raise AssertionError("CPU mode must not probe GPU")
    monkeypatch.setattr(gpu, "discover_encoders", unexpected)
    assert gpu.candidates("cpu") == ()


@pytest.mark.parametrize("vendor", ["nvidia", "intel", "amd"])
def test_gpu_keeps_timed_drawings_in_complex_filter(monkeypatch, tmp_path, vendor):
    monkeypatch.setattr(gpu, "candidates", lambda _: tuple(e for e in gpu.ENCODERS if e.vendor==vendor))
    calls=[]
    assert gpu.try_encode("source.mp4", tmp_path/"clip.mp4", seek=[],
                          filters="drawbox=x=0:y=0:w=10:h=10", overlays=[(tmp_path/"ink.png",1,3)], freeze=(1,2,True),
                          hardware_decode=True, preference="auto", run=lambda command,**_: calls.append(command),
                          progress_duration=None, progress_callback=None)
    command=calls[0]
    assert "-vf" not in command
    graph=command[command.index("-filter_complex")+1]
    assert "gte(t,1.000000)*lt(t,3.000000)" in graph
    assert "drawbox" in graph and "format=nv12" in graph
    assert "tpad=stop_mode=clone:stop_duration=2.000000" in graph
    assert "[pausedaudio]" in command
    assert command[command.index("-map")+1]=="[composed]"
    assert gpu._last_operation["software_filters"]


def test_hardware_disabled_skips_decoder(monkeypatch, tmp_path):
    monkeypatch.setattr(gpu, "candidates", lambda _: (gpu.ENCODERS[2],))
    calls = []
    def run(command, **kwargs):
        calls.append(command)
    assert gpu.try_encode("in.mp4", tmp_path / "out.mp4", seek=[], filters=None,
                          hardware_decode=False, preference="auto", run=run,
                          progress_duration=None, progress_callback=None)
    assert "-hwaccel" not in calls[0]


def test_desktop_environment_uses_auto_and_preserves_single_worker(monkeypatch, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from desktop.launcher import configure_environment, load_config
    monkeypatch.chdir(tmp_path)
    import os
    monkeypatch.setattr(os, "environ", dict(os.environ))
    configure_environment(tmp_path, load_config(tmp_path))
    assert os.environ["MEDIA_ACCELERATION"] == "auto"
    assert os.environ["FORCE_HARDWARE"] == ""
    assert os.environ["BACKGROUND_WORKERS"] == "1"
    assert os.environ["AI_ENABLED"] == "false"
