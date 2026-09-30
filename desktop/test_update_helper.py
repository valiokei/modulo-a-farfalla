import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.update_helper import run


def test_helper_rejects_non_installer_before_waiting_for_process(tmp_path):
    installer_dir = tmp_path / "ModuloAFarfalla-update-test"
    helper_dir = tmp_path / "ModuloAFarfalla-updater-test"
    installer_dir.mkdir()
    helper_dir.mkdir()
    app = tmp_path / "ModuloAFarfalla.exe"
    app.write_bytes(b"test")
    installer = installer_dir / "not-an-installer.exe"
    installer.write_bytes(b"not executable")
    assert run(installer, 123, app, helper_dir) == 2


def test_helper_rejects_unexpected_helper_directory_before_waiting_for_process(tmp_path):
    installer_dir = tmp_path / "ModuloAFarfalla-update-test"
    installer_dir.mkdir()
    installer = installer_dir / "Modulo-a-Farfalla-Setup-test-x64.exe"
    installer.write_bytes(b"not executable")
    app = tmp_path / "ModuloAFarfalla.exe"
    app.write_bytes(b"test")
    bad_helper_dir = tmp_path / "not-updater"
    bad_helper_dir.mkdir()
    assert run(installer, 123, app, bad_helper_dir) == 2
