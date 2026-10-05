import json
import sys
from pathlib import Path
import zipfile
from io import BytesIO

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.diagnostics import Diagnostics


def test_profiles_and_export_allowlist(tmp_path):
    diagnostics = Diagnostics(tmp_path)
    assert diagnostics.profile() == "production"
    diagnostics.event("api_request", operation="read", status=200)
    assert not (tmp_path / "logs" / "diagnostics.jsonl").read_text()
    diagnostics.set_profile("diagnostic")
    diagnostics.event("api_request", operation="read", status=200,
                      player_name="Private Player", password="secret-value")
    for handler in diagnostics.logger.handlers:
        handler.flush()
    data = diagnostics.export("test-build")
    assert b"Private Player" not in data and b"secret-value" not in data
    with zipfile.ZipFile(BytesIO(data)) as archive:
        assert set(archive.namelist()) == {"manifest.json", "diagnostics.jsonl"}
        events = [json.loads(line) for line in archive.read("diagnostics.jsonl").splitlines()]
        assert events[-1]["event"] == "api_request"
        assert events[-1]["status"] == 200
        assert "player_name" not in events[-1]


def test_invalid_profile_is_rejected(tmp_path):
    diagnostics = Diagnostics(tmp_path)
    with pytest.raises(ValueError):
        diagnostics.set_profile("dump_everything")


def test_levels_and_rotation_keep_only_bounded_allowlisted_events(tmp_path):
    diagnostics = Diagnostics(tmp_path)
    handler = diagnostics.logger.handlers[0]
    handler.maxBytes = 180
    diagnostics.event("api_failed", status=503, error_code="server", player_name="Never export")
    diagnostics.event("api_write", status=201)
    diagnostics.set_profile("simple")
    diagnostics.event("api_write", status=201)
    diagnostics.event("api_request", status=200)
    diagnostics.set_profile("diagnostic")
    for _ in range(20):
        diagnostics.event("api_request", operation="read", status=200, duration_ms=8,
                          request_path="/private/player-name")
    handler.flush()
    with zipfile.ZipFile(BytesIO(diagnostics.export("test-build"))) as archive:
        names = archive.namelist()
        assert len(names) <= 4
        lines = b"".join(archive.read(name) for name in names if name.endswith(".jsonl"))
        assert b"Never export" not in lines
        assert b"/private/player-name" not in lines
        assert b'"event":"api_request"' in lines
