"""On-demand AI runtime: checksum-verified download and safe extraction.

The desktop build ships without the AI runtime (portable Python + site-packages
+ model cache, roughly 2 GB). This module installs that payload from a
dedicated public GitHub release on explicit user request; the launcher then
points the backend at it through AI_PYTHON / AI_PYTHONPATH / AI_HF_HOME.
Components are downloaded to a staging folder, verified against the SHA-256
digests in the release manifest, extracted with the tarfile "data" filter
(path-traversal and link safe) and recorded with per-target receipts so an
interrupted installation resumes without re-downloading finished parts.

Each supported platform has its own pack: a dedicated prerelease tag and
manifest name, so the two runtimes never share an asset namespace and the app
updater (which only reads /releases/latest) can never mistake either of them
for an application release.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tarfile
import threading
import time

from desktop import update

logger = logging.getLogger(__name__)

# One entry per packaged desktop platform. The manifest "platform" field and
# the asset names carry the same identifier, so a Windows client can never
# install a Linux pack even if the release were pointed at the wrong tag.
PACKS = {
    "win64": {"tag": "ai-runtime-win64-1",
              "manifest": "Modulo-a-Farfalla-AI-Win64-manifest.json"},
    "linux-x64": {"tag": "ai-runtime-linux-x64-1",
                  "manifest": "Modulo-a-Farfalla-AI-Linux-x64-manifest.json"},
}


def _detect_platform() -> str:
    """Return the pack identifier for this host, or "" when unsupported."""
    machine = platform.machine().lower()
    if os.name == "nt":
        return "win64" if machine in {"amd64", "x86_64"} else ""
    if sys.platform.startswith("linux") and machine == "x86_64":
        return "linux-x64"
    # macOS and ARM builds have no pack: the desktop app keeps the "AI not
    # included" behaviour instead of offering a download that cannot work.
    return ""


PLATFORM = _detect_platform()
RUNTIME_TAG = PACKS[PLATFORM]["tag"] if PLATFORM else ""
MANIFEST_NAME = PACKS[PLATFORM]["manifest"] if PLATFORM else ""
TARGETS = ("python", "site-packages", "hf")
ARCHIVES = {"tar.gz": "r:gz", "tar.xz": "r:xz"}
MAX_COMPONENT_BYTES = 3 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1_048_576
NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
BUSY = {"starting", "downloading", "verifying", "extracting"}

_lock = threading.Lock()
_state = {"phase": "idle", "component": "", "progress": 0, "downloaded_bytes": 0,
          "total_bytes": 0, "error": "", "version": ""}


def supported() -> bool:
    # A platform is supported only when its pack is described in PACKS, so the
    # UI never offers a download that the release pipeline cannot serve.
    return bool(PLATFORM)


def paths(root: Path) -> dict:
    ai = root / "ai"
    executable = ("python.exe",) if PLATFORM == "win64" else ("bin", "python3")
    return {"python": ai.joinpath("python", *executable),
            "pythonpath": ai / "site-packages", "hf": ai / "hf"}


def _set(**values: object) -> None:
    with _lock:
        _state.update(values)


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def _release() -> dict:
    # Operational note: this release must be published as a GitHub *prerelease*;
    # /releases/latest only returns non-prerelease releases, so the app updater
    # in desktop/update.py keeps seeing the real application releases.
    with update._api_request(update.API + "/releases/tags/" + RUNTIME_TAG) as response:
        try:
            release = json.loads(response.read(1_000_000))
        except (ValueError, UnicodeError) as exc:
            raise update.UpdateError("GitHub returned invalid AI runtime metadata", "metadata") from exc
    if (not isinstance(release, dict) or release.get("tag_name") != RUNTIME_TAG
            or release.get("html_url") != f"{update.RELEASES}/tag/{RUNTIME_TAG}"):
        raise update.UpdateError("GitHub returned an unexpected AI runtime release", "metadata")
    return release


def _asset(release: dict, name: str) -> dict:
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        raise update.UpdateError("GitHub returned invalid AI runtime metadata", "metadata")
    asset = next((item for item in assets if isinstance(item, dict) and item.get("name") == name), None)
    if not asset:
        raise update.UpdateError("AI runtime release is missing " + name, "asset")
    expected = f"{update.API}/releases/assets/{asset.get('id')}"
    if not re.fullmatch(r"[0-9]+", str(asset.get("id", ""))) or asset.get("url") != expected:
        raise update.UpdateError("GitHub returned an unexpected AI runtime asset", "asset")
    if asset.get("state") not in (None, "uploaded"):
        raise update.UpdateError("AI runtime asset is not available", "asset")
    return asset


def _manifest(release: dict) -> dict:
    payload = update._asset_bytes(_asset(release, MANIFEST_NAME), limit=MAX_MANIFEST_BYTES)
    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise update.UpdateError("AI runtime manifest is invalid", "metadata") from exc
    if not isinstance(data, dict) or data.get("format") != 1 or data.get("platform") != PLATFORM:
        raise update.UpdateError("AI runtime manifest is invalid", "metadata")
    raw_components = data.get("components")
    if not isinstance(raw_components, list):
        raise update.UpdateError("AI runtime manifest is invalid", "metadata")
    components, targets = [], set()
    for raw in raw_components:
        target, name = (raw.get("target"), raw.get("asset")) if isinstance(raw, dict) else (None, None)
        digest, size, archive = (raw.get("sha256"), raw.get("size"), raw.get("archive")) if isinstance(raw, dict) else (None, None, None)
        if (target not in TARGETS or target in targets or not isinstance(name, str)
                or not NAME_PATTERN.fullmatch(name) or not isinstance(digest, str)
                or not SHA256_PATTERN.fullmatch(digest) or archive not in ARCHIVES
                or not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_COMPONENT_BYTES):
            raise update.UpdateError("AI runtime manifest is invalid", "metadata")
        targets.add(target)
        components.append({"target": target, "asset": name, "sha256": digest.lower(), "size": size, "archive": archive})
    if targets != set(TARGETS):
        raise update.UpdateError("AI runtime manifest is incomplete", "metadata")
    return {"version": str(data.get("version", ""))[:64], "components": components}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _receipt_valid(receipts: Path, target: str, digest: str) -> bool:
    try:
        value = json.loads((receipts / f"{target}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(value, dict) and value.get("format") == 1 and value.get("sha256") == digest


def _present(ai: Path, target: str) -> bool:
    try:
        return (ai / target).is_dir() and any((ai / target).iterdir())
    except OSError:
        return False


def _download(asset: dict, size: int, digest_pattern: str, destination: Path, on_bytes) -> None:
    try:
        declared = int(asset.get("size", 0))
    except (TypeError, ValueError) as exc:
        raise update.UpdateError("AI runtime asset has an invalid size", "asset") from exc
    if declared != size or declared <= 0 or declared > MAX_COMPONENT_BYTES:
        raise update.UpdateError("AI runtime asset size does not match its manifest", "asset")
    response = update._asset_open(asset)
    try:
        digest = hashlib.sha256()
        total = 0
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > declared:
                    raise update.UpdateError("AI runtime download exceeded its declared size", "asset")
                digest.update(chunk)
                output.write(chunk)
                on_bytes(total)
        if total != declared:
            raise update.UpdateError("AI runtime download size did not match the release metadata", "asset")
        if digest.hexdigest().lower() != digest_pattern:
            raise update.UpdateError("AI runtime download failed SHA-256 verification", "asset")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        response.close()


def _extract(archive: Path, destination: Path, archive_format: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    mode = "r:xz" if archive_format == "tar.xz" else "r:gz"
    try:
        with tarfile.open(archive, mode) as payload:
            for member in payload:
                # filter="data" rejects absolute paths, traversal and unsafe
                # links, so a corrupted release cannot write outside the target.
                payload.extract(member, destination, filter="data")
    except (tarfile.TarError, OSError, EOFError, ValueError) as exc:
        raise update.UpdateError("AI runtime archive could not be extracted", "extract") from exc


def _installed(ai: Path) -> bool:
    try:
        value = json.loads((ai / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    targets = value.get("targets", {})
    return (value.get("format") == 1 and isinstance(targets, dict) and set(TARGETS) <= set(targets)
            and all(_present(ai, target) for target in TARGETS))


def install(root: Path) -> None:
    """Synchronous installer worker; start() runs it on a background thread."""
    try:
        if not supported():
            raise update.UpdateError("The on-demand AI runtime is not available on this platform", "unsupported")
        ai = root / "ai"
        if _installed(ai):
            _set(phase="ready", progress=100, error="")
            return
        release = _release()
        manifest = _manifest(release)
        components = manifest["components"]
        total = sum(component["size"] for component in components)
        receipts = ai / ".receipts"
        downloads = ai / ".download"
        downloads.mkdir(parents=True, exist_ok=True)
        receipts.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(ai).free < total * 5 // 2 + 256 * 1024 * 1024:
            raise update.UpdateError("Not enough free disk space for the AI runtime", "disk")
        _set(phase="downloading", component="", progress=0, downloaded_bytes=0, total_bytes=total,
             error="", version=manifest["version"])
        done = 0
        for component in components:
            target, name = component["target"], component["asset"]
            digest, size, archive_format = component["sha256"], component["size"], component["archive"]
            if _receipt_valid(receipts, target, digest) and _present(ai, target):
                done += size
                continue
            _set(component=target, progress=min(99, 100 * done // total))
            archive = downloads / name
            if not (archive.is_file() and archive.stat().st_size == size and _sha256(archive) == digest):
                _download(_asset(release, name), size, digest, archive,
                          lambda count, base=done: _set(downloaded_bytes=base + count,
                                                        progress=min(99, 100 * (base + count) // total)))
            _set(phase="extracting", downloaded_bytes=done + size)
            shutil.rmtree(ai / target, ignore_errors=True)
            _extract(archive, ai / target, archive_format)
            _atomic_json(receipts / f"{target}.json", {"format": 1, "sha256": digest, "extracted_at": int(time.time())})
            archive.unlink(missing_ok=True)
            done += size
            _set(phase="downloading")
        _atomic_json(ai / "installed.json", {"format": 1, "version": manifest["version"], "platform": PLATFORM,
                                             "installed_at": int(time.time()), "size_bytes": total,
                                             "targets": {component["target"]: component["size"] for component in components}})
        shutil.rmtree(downloads, ignore_errors=True)
        _set(phase="ready", component="", progress=100, error="")
    except update.UpdateError as exc:
        logger.warning("AI runtime installation failed: %s (%s)", exc, exc.code)
        _set(phase="failed", error=exc.code)
    except Exception:
        logger.exception("AI runtime installation failed")
        _set(phase="failed", error="unexpected")


def status(root: Path) -> dict:
    ai = root / "ai"
    result = dict(_state)
    result["supported"] = supported()
    if _installed(ai):
        result.update(phase="ready", progress=100, error="")
        try:
            value = json.loads((ai / "installed.json").read_text(encoding="utf-8"))
            result["version"] = str(value.get("version", ""))[:64]
            result["size_bytes"] = int(value.get("size_bytes", 0))
        except (OSError, ValueError, TypeError):
            pass
        return result
    if result["phase"] in BUSY or result["phase"] == "failed":
        return result
    try:
        leftover = ai.is_dir() and any(ai.iterdir())
    except OSError:
        leftover = False
    result["phase"] = "partial" if leftover else "not_installed"
    return result


def start(root: Path) -> dict:
    with _lock:
        if _state["phase"] not in BUSY and status(root)["phase"] != "ready":
            _state.update(phase="starting", component="", progress=0, downloaded_bytes=0, total_bytes=0,
                          error="", version="")
            threading.Thread(target=install, args=(root,), name="ai-runtime", daemon=True).start()
    return status(root)


def remove(root: Path) -> None:
    with _lock:
        if _state["phase"] in BUSY:
            raise RuntimeError("An AI runtime installation is in progress")
    shutil.rmtree(root / "ai", ignore_errors=True)
    _set(phase="idle", component="", progress=0, downloaded_bytes=0, total_bytes=0, error="", version="")
