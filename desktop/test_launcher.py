import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.launcher import InstanceLock, atomic_json, load_config, TEXT


def test_configuration_is_persistent_and_unique(tmp_path):
    first = load_config(tmp_path)
    assert first == load_config(tmp_path)
    assert first["initialized"] is False
    other = tmp_path / "other"
    other.mkdir()
    assert first["secret_key"] != load_config(other)["secret_key"]
    assert len(first["bootstrap_password"]) > 40
    if os.name != "nt":
        assert (tmp_path / "desktop.json").stat().st_mode & 0o777 == 0o600


def test_invalid_config_is_not_replaced(tmp_path):
    atomic_json(tmp_path / "desktop.json", {"version": 99})
    before = (tmp_path / "desktop.json").read_bytes()
    with pytest.raises(ValueError):
        load_config(tmp_path)
    assert (tmp_path / "desktop.json").read_bytes() == before


def test_single_instance(tmp_path):
    first = InstanceLock(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="instance_locked"):
            InstanceLock(tmp_path)
    finally:
        first.close()
    InstanceLock(tmp_path).close()


def test_translations_have_same_keys():
    assert TEXT["it"].keys() == TEXT["en"].keys()


def test_windows_ffmpeg_uses_creation_flags(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app import media
    monkeypatch.setattr(media.os, "name", "nt")
    monkeypatch.setattr(media.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(media.subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000, raising=False)
    assert media.subprocess_options() == {"creationflags": 0x08004000}
