import hashlib
import io
import socket
import ssl
import sys
from pathlib import Path
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop import update


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def release_payload(tag="windows-20260930-def5678", url=None):
    release_url = url or f"{update.RELEASES}/tag/{tag}"
    return ("{\"tag_name\":\"" + tag + "\",\"html_url\":\"" + release_url + "\","
            "\"assets\":["
            "{\"id\":1,\"url\":\"" + update.API + "/releases/assets/1\","
            "\"state\":\"uploaded\",\"name\":\"Modulo-a-Farfalla-Setup-def5678-x64.exe\",\"size\":10},"
            "{\"id\":2,\"url\":\"" + update.API + "/releases/assets/2\","
            "\"state\":\"uploaded\",\"name\":\"Modulo-a-Farfalla-Setup-def5678-x64.exe.sha256\",\"size\":80}]}"
            ).encode()


def test_public_release_uses_no_token_and_requires_expected_assets(monkeypatch):
    monkeypatch.setattr(update, "build_version", lambda: "abc1234")
    seen = {}

    def fake_request(url, *, accept="application/vnd.github+json"):
        seen["url"] = url
        seen["accept"] = accept
        return Response(release_payload())

    monkeypatch.setattr(update, "_api_request", fake_request)
    release = update.latest_release()
    assert seen["url"] == update.API + "/releases/latest"
    assert release["update_available"] is True
    assert release["latest_version"] == "windows-20260930-def5678"
    public = update.public_release(release)
    assert "installer" not in public and "checksum" not in public
    assert public["release_url"] == f"{update.RELEASES}/tag/windows-20260930-def5678"


def test_unexpected_repository_release_is_rejected(monkeypatch):
    monkeypatch.setattr(update, "_api_request", lambda *_a, **_k:
                        Response(release_payload(url="https://github.com/attacker/repo/releases/tag/windows-20260930-def5678")))
    with pytest.raises(update.UpdateError, match="unexpected release"):
        update.latest_release()


def test_latest_release_without_windows_assets_is_rejected(monkeypatch):
    body = (f'{{"tag_name":"windows-20260930-def5678","html_url":"{update.RELEASES}'
            '/tag/windows-20260930-def5678","assets":[]}').encode()
    monkeypatch.setattr(update, "_api_request", lambda *_a, **_k: Response(body))
    with pytest.raises(update.UpdateError, match="no supported Windows x64 installer"):
        update.latest_release()


def test_public_api_request_has_no_authorization_header(monkeypatch):
    captured = {}

    class Opener:
        def open(self, request, timeout):
            captured["headers"] = {key.lower(): value for key, value in request.header_items()}
            return Response(b"{}")

    monkeypatch.setattr(update.urllib.request, "build_opener", lambda *_: Opener())
    with update._api_request(update.API + "/releases/latest"):
        pass
    assert "authorization" not in captured["headers"]


def test_public_api_network_failure_is_reported(monkeypatch):
    class Opener:
        def open(self, *_a, **_k):
            raise urllib.error.URLError("offline")
    monkeypatch.setattr(update.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(update.UpdateError, match="api.github.com"):
        update._api_request(update.API + "/releases/latest")


@pytest.mark.parametrize("reason,code", [
    ("proxy connection refused", "proxy"),
    (TimeoutError(), "timeout"),
    ("connection timed out", "timeout"),
    (socket.gaierror(-2, "host not found"), "dns"),
    (ssl.SSLError("certificate verify failed"), "tls"),
])
def test_network_failure_categories(reason, code):
    assert update.network_error(urllib.error.URLError(reason)).code == code


def test_invalid_release_has_distinct_error_code(monkeypatch):
    monkeypatch.setattr(update, "_api_request", lambda *_a, **_k: Response(b"not json"))
    with pytest.raises(update.UpdateError) as caught:
        update.latest_release()
    assert caught.value.code == "metadata"


def test_http_proxy_auth_has_distinct_error_code(monkeypatch):
    class Opener:
        def open(self, *_a, **_k):
            raise urllib.error.HTTPError(update.API, 407, "Proxy Authentication Required", {}, None)
    monkeypatch.setattr(update.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(update.UpdateError) as caught:
        update._api_request(update.API + "/releases/latest")
    assert caught.value.code == "proxy"


def test_release_requires_exact_windows_tag_asset_pair(monkeypatch):
    monkeypatch.setattr(update, "_api_request", lambda *_a, **_k:
                        Response(release_payload(tag="latest")))
    with pytest.raises(update.UpdateError, match="unexpected release"):
        update.latest_release()


@pytest.mark.parametrize("checksum_name", ["wrong.exe", ""])
def test_invalid_checksum_name_removes_installer(monkeypatch, tmp_path, checksum_name):
    content = b"public windows installer bytes"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(update, "_asset_open", lambda *_: Response(content))
    monkeypatch.setattr(update, "_asset_bytes", lambda *_a, **_k:
                        f"{digest}  {checksum_name}".encode())
    path = tmp_path / "Modulo-a-Farfalla-Setup-def5678-x64.exe"
    asset = {"size": len(content), "name": path.name,
             "checksum": {"id": "2", "name": path.name + ".sha256"}}
    with pytest.raises(update.UpdateError, match="checksum file"):
        update._asset_download(asset, path)
    assert not path.exists()


def test_valid_checksum_and_size_are_required(monkeypatch, tmp_path):
    content = b"public windows installer bytes"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(update, "_asset_open", lambda *_: Response(content))
    monkeypatch.setattr(update, "_asset_bytes", lambda *_a, **_k:
                        f"{digest}  Modulo-a-Farfalla-Setup-def5678-x64.exe".encode())
    path = tmp_path / "Modulo-a-Farfalla-Setup-def5678-x64.exe"
    asset = {"size": len(content), "name": path.name,
             "checksum": {"id": "2", "url": f"{update.API}/releases/assets/2",
                          "name": path.name + ".sha256"}}
    update._asset_download(asset, path)
    assert path.read_bytes() == content


def test_checksum_mismatch_removes_downloaded_installer(monkeypatch, tmp_path):
    content = b"installer whose digest will not match"
    monkeypatch.setattr(update, "_asset_open", lambda *_: Response(content))
    monkeypatch.setattr(update, "_asset_bytes", lambda *_a, **_k:
                        ("0" * 64 + "  Modulo-a-Farfalla-Setup-def5678-x64.exe").encode())
    path = tmp_path / "Modulo-a-Farfalla-Setup-def5678-x64.exe"
    asset = {"size": len(content), "name": path.name,
             "checksum": {"id": "2", "name": path.name + ".sha256"}}
    with pytest.raises(update.UpdateError, match="SHA-256 verification failed"):
        update._asset_download(asset, path)
    assert not path.exists()


def test_unexpected_asset_url_is_rejected(monkeypatch):
    monkeypatch.setattr(update, "_api_request", lambda *_a, **_k: pytest.fail("request should not happen"))
    with pytest.raises(update.UpdateError, match="Unexpected update asset URL"):
        update._asset_open({"id": 12, "url": "https://attacker.example/asset"})


def test_unexpected_asset_redirect_host_is_rejected(monkeypatch):
    class Redirect:
        status = 302
        headers = {"Location": "https://attacker.example/setup.exe"}
        close = lambda self: None
    monkeypatch.setattr(update, "_api_request", lambda *_a, **_k: Redirect())
    with pytest.raises(update.UpdateError, match="unexpected installer host"):
        update._asset_open({"id": 12, "url": f"{update.API}/releases/assets/12"})
