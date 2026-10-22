import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import ai_runtime, update


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def make_tar(member: str, payload: bytes) -> bytes:
    """A tiny gzip tarball whose entry names carry no target prefix: extraction
    happens into ai/<target>, matching how the real pack is built (tar -C dir)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as raw:
        info = tarfile.TarInfo(member)
        info.size = len(payload)
        raw.addfile(info, io.BytesIO(payload))
    return gzip.compress(buffer.getvalue())


def make_manifest(archives: dict, *, archive="tar.gz") -> bytes:
    """Manifest computed from the exact bytes that the fake release serves."""
    parts = []
    for name, content in archives.items():
        digest = hashlib.sha256(content).hexdigest()
        parts.append({"target": name.rsplit(".", 2)[0], "asset": name,
                      "sha256": digest, "size": len(content), "archive": archive})
    manifest = {"format": 1, "platform": ai_runtime.PLATFORM, "version": "test-1",
                "components": parts}
    return json.dumps(manifest).encode()


class FakeAsset:
    """Routes update's asset/API helpers to locally built release bytes."""

    def __init__(self, manifest_bytes, archives):
        self.manifest_bytes = manifest_bytes
        self.archives = archives
        self.opened = []

    def open(self, asset, *, limit=None):
        name = asset.get("name")
        self.opened.append(name)
        if name == ai_runtime.MANIFEST_NAME:
            return Response(self.manifest_bytes)
        return Response(self.archives[name])

    def api_request(self, url, **_k):
        if not url.endswith("/releases/tags/" + ai_runtime.RUNTIME_TAG):
            raise AssertionError("unexpected API request: " + url)
        names = [ai_runtime.MANIFEST_NAME, *self.archives]
        payload = {"tag_name": ai_runtime.RUNTIME_TAG,
                   "html_url": f"{update.RELEASES}/tag/{ai_runtime.RUNTIME_TAG}",
                   "assets": [{"id": str(index + 1), "name": name, "state": "uploaded",
                               "url": f"{update.API}/releases/assets/{index + 1}",
                               "size": len(self.archives.get(name, self.manifest_bytes))}
                              for index, name in enumerate(names)]}
        return Response(json.dumps(payload).encode())


def wire(monkeypatch, contents, archive="tar.gz"):
    """Build fake release bytes from raw payloads; returns the FakeAsset router."""
    built = {f"{target}.{archive}": make_tar("marker.bin", payload)
             for target, payload in contents.items()}
    router = FakeAsset(make_manifest(built, archive=archive), built)
    monkeypatch.setattr(update, "_asset_open", router.open)
    monkeypatch.setattr(update, "_api_request", router.api_request)
    monkeypatch.setattr(ai_runtime, "supported", lambda: True)
    monkeypatch.setattr(ai_runtime.shutil, "disk_usage",
                        lambda _p: type("U", (), {"free": 16 * 1024 ** 3})())
    return router


@pytest.fixture(autouse=True)
def fresh_state():
    ai_runtime._state.update(phase="idle", component="", progress=0, downloaded_bytes=0,
                             total_bytes=0, error="", version="")
    yield


def test_install_downloads_verifies_extracts_and_records(tmp_path, monkeypatch):
    wire(monkeypatch, {target: f"content-{target}".encode() for target in ai_runtime.TARGETS})
    ai_runtime.install(tmp_path)
    state = ai_runtime.status(tmp_path)
    assert state["phase"] == "ready" and state["error"] == ""
    assert (tmp_path / "ai" / "installed.json").is_file()
    for target in ai_runtime.TARGETS:
        assert (tmp_path / "ai" / target / "marker.bin").read_bytes() == f"content-{target}".encode()
    assert not (tmp_path / "ai" / ".download").exists()
    assert json.loads((tmp_path / "ai" / ".receipts" / "python.json").read_text())["format"] == 1
    ai_runtime.remove(tmp_path)
    assert ai_runtime.status(tmp_path)["phase"] == "not_installed"


def test_install_resumes_after_a_failed_component(tmp_path, monkeypatch):
    router = wire(monkeypatch, {target: f"content-{target}".encode() for target in ai_runtime.TARGETS})
    original = router.open

    def fail_second(asset, *, limit=None):
        if asset.get("name") == "site-packages.tar.gz":
            raise update.UpdateError("simulated network drop", "timeout")
        return original(asset, limit=limit)

    monkeypatch.setattr(update, "_asset_open", fail_second)
    ai_runtime.install(tmp_path)
    assert ai_runtime.status(tmp_path)["phase"] == "failed"
    assert (tmp_path / "ai" / "python" / "marker.bin").is_file()
    assert not (tmp_path / "ai" / "site-packages").exists()
    # The retry must skip the finished python component and download the rest.
    router.opened.clear()
    monkeypatch.setattr(update, "_asset_open", router.open)
    ai_runtime.install(tmp_path)
    assert ai_runtime.status(tmp_path)["phase"] == "ready"
    assert "python.tar.gz" not in router.opened
    assert router.opened.count("site-packages.tar.gz") == 1
    for target in ai_runtime.TARGETS:
        assert (tmp_path / "ai" / target / "marker.bin").read_bytes() == f"content-{target}".encode()


def test_tampered_component_is_rejected(tmp_path, monkeypatch):
    router = wire(monkeypatch, {target: f"content-{target}".encode() for target in ai_runtime.TARGETS})
    manifest = json.loads(router.manifest_bytes)
    manifest["components"][0]["sha256"] = "0" * 64
    router.manifest_bytes = json.dumps(manifest).encode()
    ai_runtime.install(tmp_path)
    state = ai_runtime.status(tmp_path)
    assert state["phase"] == "failed" and state["error"] == "asset"
    assert not (tmp_path / "ai" / "installed.json").exists()


def test_manifest_rejects_incomplete_target_set(tmp_path, monkeypatch):
    router = wire(monkeypatch, {target: f"content-{target}".encode() for target in ai_runtime.TARGETS})
    manifest = json.loads(router.manifest_bytes)
    manifest["components"] = manifest["components"][:2]
    router.manifest_bytes = json.dumps(manifest).encode()
    ai_runtime.install(tmp_path)
    assert ai_runtime.status(tmp_path)["error"] == "metadata"


def test_status_reports_partial_for_leftover_files(tmp_path):
    (tmp_path / "ai" / "junk").mkdir(parents=True)
    (tmp_path / "ai" / "junk" / "file.bin").write_bytes(b"x")
    assert ai_runtime.status(tmp_path)["phase"] == "partial"
    (tmp_path / "empty").mkdir()
    assert ai_runtime.status(tmp_path / "empty")["phase"] == "not_installed"


def test_pack_selection_is_driven_by_the_platform(monkeypatch):
    """Each packaged desktop platform resolves its own prerelease tag and
    manifest, so a client can never install the other platform's runtime."""
    assert ai_runtime.PACKS["win64"]["tag"] == "ai-runtime-win64-1"
    assert ai_runtime.PACKS["linux-x64"]["tag"] == "ai-runtime-linux-x64-1"
    monkeypatch.setattr(ai_runtime.sys, "platform", "linux")
    monkeypatch.setattr(ai_runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(ai_runtime.os, "name", "posix")
    assert ai_runtime._detect_platform() == "linux-x64"
    monkeypatch.setattr(ai_runtime.platform, "machine", lambda: "aarch64")
    assert ai_runtime._detect_platform() == ""
    monkeypatch.setattr(ai_runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(ai_runtime.os, "name", "nt")
    assert ai_runtime._detect_platform() == "win64"
    monkeypatch.setattr(ai_runtime.platform, "machine", lambda: "ARM64")
    assert ai_runtime._detect_platform() == ""


def test_unsupported_platform_refuses_install_and_hides_the_button(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_runtime, "PLATFORM", "")
    monkeypatch.setattr(ai_runtime, "RUNTIME_TAG", "")
    monkeypatch.setattr(ai_runtime, "MANIFEST_NAME", "")
    assert ai_runtime.supported() is False
    assert ai_runtime.status(tmp_path)["supported"] is False
    ai_runtime.install(tmp_path)
    state = ai_runtime.status(tmp_path)
    assert state["phase"] == "failed" and state["error"] == "unsupported"
    assert not (tmp_path / "ai").exists()


def test_paths_match_the_pack_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_runtime, "PLATFORM", "win64")
    assert ai_runtime.paths(tmp_path)["python"].as_posix().endswith("ai/python/python.exe")
    monkeypatch.setattr(ai_runtime, "PLATFORM", "linux-x64")
    targets = ai_runtime.paths(tmp_path)
    assert targets["python"].as_posix().endswith("ai/python/bin/python3")
    assert targets["pythonpath"] == tmp_path / "ai" / "site-packages"
    assert targets["hf"] == tmp_path / "ai" / "hf"


def test_installed_requires_every_target_and_content(tmp_path):
    (tmp_path / "ai").mkdir()
    (tmp_path / "ai" / "installed.json").write_text(json.dumps(
        {"format": 1, "targets": {target: 1 for target in ai_runtime.TARGETS}}))
    for target in ai_runtime.TARGETS:
        (tmp_path / "ai" / target).mkdir()
        (tmp_path / "ai" / target / "marker.bin").write_bytes(b"m")
    assert ai_runtime._installed(tmp_path / "ai") is True
    (tmp_path / "ai" / "hf" / "marker.bin").unlink()
    assert ai_runtime._installed(tmp_path / "ai") is False


def test_extract_rejects_path_traversal(tmp_path):
    hostile = tmp_path / "hostile.tar.gz"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as raw:
        info = tarfile.TarInfo("../../etc/escape")
        info.size = 1
        raw.addfile(info, io.BytesIO(b"x"))
    hostile.write_bytes(gzip.compress(buffer.getvalue()))
    with pytest.raises(update.UpdateError, match="could not be extracted"):
        ai_runtime._extract(hostile, tmp_path / "out", "tar.gz")
    assert not (tmp_path / "etc").exists()


def test_download_rejects_size_mismatch_and_leaves_no_partial_file(tmp_path, monkeypatch):
    content = b"x" * 100
    monkeypatch.setattr(update, "_asset_open", lambda *_: Response(content))
    asset = {"name": "python.tar.gz", "id": "1", "url": f"{update.API}/releases/assets/1", "size": 5}
    destination = tmp_path / "python.tar.gz"
    with pytest.raises(update.UpdateError, match="size"):
        ai_runtime._download(asset, 100, hashlib.sha256(content).hexdigest(), destination, lambda n: None)
    assert not destination.exists()


def test_download_rejects_checksum_mismatch(tmp_path, monkeypatch):
    content = b"x" * 100
    monkeypatch.setattr(update, "_asset_open", lambda *_: Response(content))
    asset = {"name": "python.tar.gz", "id": "1", "url": f"{update.API}/releases/assets/1", "size": 100}
    destination = tmp_path / "python.tar.gz"
    with pytest.raises(update.UpdateError, match="SHA-256"):
        ai_runtime._download(asset, 100, "0" * 64, destination, lambda n: None)
    assert not destination.exists()


def test_start_is_idempotent_while_busy_and_remove_blocks_then_clears(tmp_path, monkeypatch):
    wire(monkeypatch, {target: b"c" for target in ai_runtime.TARGETS})
    spawns = []
    monkeypatch.setattr(ai_runtime.threading, "Thread",
                        lambda *a, **k: spawns.append(a) or type("T", (), {"start": lambda self: None,
                                                                          "is_alive": lambda self: True})())
    ai_runtime._set(phase="downloading")
    assert ai_runtime.start(tmp_path)["phase"] == "downloading" and not spawns
    with pytest.raises(RuntimeError, match="in progress"):
        ai_runtime.remove(tmp_path)
    ai_runtime._set(phase="idle")
    ai_runtime.remove(tmp_path)
    assert ai_runtime.status(tmp_path)["phase"] == "not_installed"


def test_start_spawns_once_when_idle(tmp_path, monkeypatch):
    wire(monkeypatch, {target: b"c" for target in ai_runtime.TARGETS})
    started = []
    monkeypatch.setattr(ai_runtime.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: started.append(a),
                                                       "is_alive": lambda self: True})())
    state = ai_runtime.start(tmp_path)
    assert state["phase"] in ai_runtime.BUSY and started
