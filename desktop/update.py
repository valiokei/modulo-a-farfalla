"""Unauthenticated, checksum-verified updater for public Windows releases."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
import urllib.error
import urllib.request

OWNER = "valiokei"
REPOSITORY = "modulo-a-farfalla"
API = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}"
RELEASES = f"https://github.com/{OWNER}/{REPOSITORY}/releases"
MAX_INSTALLER_BYTES = 500 * 1024 * 1024
INSTALLER_NAME = re.compile(r"^Modulo-a-Farfalla-Setup-[A-Za-z0-9._-]+-x64\.exe$")


class UpdateError(RuntimeError):
    pass


def build_version() -> str:
    try:
        return (Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) /
                "build-version.txt").read_text(encoding="ascii").strip()
    except OSError:
        return "development"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GithubAssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
            raise UpdateError("GitHub returned an unexpected installer host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _api_request(url: str, *, accept: str = "application/vnd.github+json"):
    if not url.startswith(API + "/"):
        raise UpdateError("Unexpected update URL")
    request = urllib.request.Request(url, headers={"Accept": accept,
                              "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ModuloAFarfalla-Updater"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        return opener.open(request, timeout=20)
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return exc
        if exc.code in (401, 403, 404):
            raise UpdateError("The public GitHub release is unavailable") from None
        raise UpdateError(f"GitHub update request failed (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UpdateError("Could not reach GitHub to check updates") from exc


def latest_release() -> dict:
    with _api_request(API + "/releases/latest") as response:
        try:
            release = json.loads(response.read(1_000_000))
        except (ValueError, UnicodeError) as exc:
            raise UpdateError("GitHub returned invalid release metadata") from exc
    if not isinstance(release, dict):
        raise UpdateError("GitHub returned invalid release metadata")
    tag = str(release.get("tag_name", ""))
    tag_match = re.fullmatch(r"windows-[0-9]{8}-([0-9a-fA-F]{7,40})", tag)
    expected_release_url = f"{RELEASES}/tag/{tag}"
    if not tag_match or release.get("html_url") != expected_release_url:
        raise UpdateError("GitHub returned an unexpected release")
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        raise UpdateError("GitHub returned invalid release metadata")
    installer = next((asset for asset in assets if isinstance(asset, dict)
                      and INSTALLER_NAME.fullmatch(asset.get("name", ""))), None)
    if not installer:
        raise UpdateError("Latest public release has no supported Windows x64 installer")
    checksum = next((asset for asset in assets if isinstance(asset, dict)
                     and asset.get("name") == installer["name"] + ".sha256"), None)
    if not checksum:
        raise UpdateError("Latest release is missing its installer SHA-256 file")
    if not tag_match or not installer["name"].endswith(f"-{tag_match.group(1)}-x64.exe"):
        raise UpdateError("Latest release tag does not match the Windows release format")
    for asset in (installer, checksum):
        expected_url = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/assets/{asset.get('id')}"
        if not re.fullmatch(r"[0-9]+", str(asset.get("id", ""))) or asset.get("url") != expected_url:
            raise UpdateError("GitHub returned an unexpected release asset")
        if asset.get("state") not in (None, "uploaded"):
            raise UpdateError("GitHub release asset is not available")
    current = build_version()
    latest_commit = tag_match.group(1)
    return {"current_version": current, "latest_version": tag,
            "update_available": current != "development" and latest_commit.lower() != current.lower(),
            "release_url": expected_release_url, "name": release.get("name") or tag,
            "installer": installer, "checksum": checksum}


def public_release(release: dict) -> dict:
    return {key: release[key] for key in
            ("current_version", "latest_version", "update_available", "release_url", "name")}


def _asset_open(asset: dict):
    if not re.fullmatch(r"[0-9]+", str(asset.get("id", ""))):
        raise UpdateError("Invalid GitHub release asset")
    if asset.get("url") != f"{API}/releases/assets/{asset['id']}":
        raise UpdateError("Unexpected update asset URL")
    response = _api_request(asset["url"], accept="application/octet-stream")
    if getattr(response, "status", None) in (301, 302, 303, 307, 308):
        signed_url = response.headers.get("Location", "")
        host = urlparse(signed_url).hostname or ""
        if urlparse(signed_url).scheme != "https" or host not in {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
            response.close()
            raise UpdateError("GitHub returned an unexpected installer host")
        response.close()
        try:
            response = urllib.request.build_opener(_GithubAssetRedirect).open(
                urllib.request.Request(signed_url, headers={"User-Agent": "ModuloAFarfalla-Updater"}), timeout=60)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise UpdateError("Could not download the verified release asset") from exc
    return response


def _asset_bytes(asset: dict, *, limit: int) -> bytes:
    with _asset_open(asset) as response:
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise UpdateError("Release asset exceeds the allowed size")
    return payload


def _asset_download(asset: dict, destination: Path) -> None:
    try:
        declared_size = int(asset.get("size", 0))
    except (TypeError, ValueError) as exc:
        raise UpdateError("Installer has an invalid size") from exc
    if declared_size <= 0 or declared_size > MAX_INSTALLER_BYTES:
        raise UpdateError("Installer has an invalid or excessive size")
    response = _asset_open(asset)
    try:
        digest = hashlib.sha256()
        total = 0
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_INSTALLER_BYTES or total > declared_size:
                    raise UpdateError("Downloaded installer exceeded its declared size")
                digest.update(chunk)
                output.write(chunk)
        if total != declared_size:
            raise UpdateError("Downloaded installer size did not match GitHub metadata")
        checksum_text = _asset_bytes(asset["checksum"], limit=2048).decode("ascii", errors="strict").strip()
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", checksum_text)
        if not match or Path(match.group(2)).name != asset["name"]:
            raise UpdateError("The release checksum file is invalid")
        if digest.hexdigest().lower() != match.group(1).lower():
            raise UpdateError("Installer SHA-256 verification failed")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        response.close()


def download_verified_update() -> Path:
    release = latest_release()
    if not release["update_available"]:
        raise UpdateError("No newer Windows release is available")
    staging = Path(tempfile.mkdtemp(prefix="ModuloAFarfalla-update-"))
    installer = staging / release["installer"]["name"]
    try:
        _asset_download(release["installer"] | {"checksum": release["checksum"]}, installer)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return installer


def start_update_helper(installer: Path) -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise UpdateError("In-app installation is available in the packaged Windows app")
    source_helper = Path(sys.executable).parent / "ModuloAFarfallaUpdater.exe"
    if not source_helper.is_file():
        installer.unlink(missing_ok=True)
        installer.parent.rmdir()
        raise UpdateError("The bundled Windows updater helper is missing")
    staging = Path(tempfile.mkdtemp(prefix="ModuloAFarfalla-updater-"))
    helper = staging / source_helper.name
    try:
        shutil.copy2(source_helper, helper)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("Could not prepare the Windows installer helper") from exc
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | 0x01000000
    try:
        subprocess.Popen([str(helper), "--installer", str(installer), "--parent-pid", str(os.getpid()),
                          "--app-path", sys.executable, "--cleanup-dir", str(staging)],
                         close_fds=True, creationflags=flags, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        installer.unlink(missing_ok=True)
        installer.parent.rmdir()
        raise UpdateError("Could not start the Windows installer helper") from exc
