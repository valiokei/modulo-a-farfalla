from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH).parent
data = [(str(root / "frontend" / "dist"), "frontend"),
        (str(root / "backend" / "alembic"), "alembic"),
        (str(root / "desktop" / "build-version.txt"), "."),
        (str(root / "VERSION"), "."),
        (str(root / "desktop" / "vendor" / "ffmpeg"), "ffmpeg"),
        (str(root / "desktop" / "THIRD_PARTY_NOTICES.md"), ".")]
for package in ("alembic", "pydantic", "pydantic-settings", "pwdlib", "argon2-cffi", "sqlalchemy"):
    data += copy_metadata(package)
a = Analysis([str(root / "desktop" / "launcher.py")],
             pathex=[str(root / "backend"), str(root)], binaries=[], datas=data,
             hiddenimports=collect_submodules("app") + collect_submodules("uvicorn")
             + ["sqlalchemy.dialects.sqlite", "pwdlib.hashers.argon2", "alembic.sql.sqlite",
                "desktop.diagnostics", "desktop.update"],
             excludes=["pytest", "torch", "opensportslib"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ModuloAFarfalla", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
bundle = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ModuloAFarfalla")
