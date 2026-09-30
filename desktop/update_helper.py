"""Small detached Windows helper so setup can replace the closed app files."""
import argparse
import ctypes
from pathlib import Path
import re
import subprocess
import tempfile


INSTALLER_NAME = re.compile(r"^Modulo-a-Farfalla-Setup-[A-Za-z0-9._-]+-x64\.exe$")


def _message(text: str, *, error: bool = False) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Modulo a Farfalla", 0x10 if error else 0x40)


def run(installer: Path, parent_pid: int, app_path: Path, cleanup_dir: Path) -> int:
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        installer = installer.resolve(strict=True)
        app_path = app_path.resolve(strict=True)
        cleanup_dir = cleanup_dir.resolve(strict=True)
        installer_dir = installer.parent
    except OSError:
        return 2
    if (not INSTALLER_NAME.fullmatch(installer.name) or not installer.is_file()
            or temp_root not in installer.parents or temp_root not in cleanup_dir.parents
            or not installer_dir.name.startswith("ModuloAFarfalla-update-")
            or not cleanup_dir.name.startswith("ModuloAFarfalla-updater-")
            or app_path.name.lower() != "moduloafarfalla.exe"):
        return 2

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, parent_pid)
    if handle:
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)

    try:
        result = subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                                 f"/DIR={app_path.parent}"],
                                timeout=900, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        _message("Installazione non completata. Avvia l'app dal menu Start e riprova.", error=True)
        return 1
    if result.returncode != 0:
        _message("L'aggiornamento non è riuscito. Avvia l'app dal menu Start e riprova.", error=True)
        return result.returncode
    try:
        subprocess.Popen([str(app_path)], close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    except OSError:
        _message("Aggiornamento installato. Avvia Modulo a Farfalla dal menu Start.")
    installer.unlink(missing_ok=True)
    try:
        installer_dir.rmdir()
    except OSError:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--app-path", type=Path, required=True)
    parser.add_argument("--cleanup-dir", type=Path, required=True)
    args = parser.parse_args()
    return run(args.installer, args.parent_pid, args.app_path, args.cleanup_dir)


if __name__ == "__main__":
    raise SystemExit(main())
