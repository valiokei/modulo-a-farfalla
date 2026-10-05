"""Per-user, loopback-only desktop launcher for the existing application."""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
import threading
import time
import webbrowser

ADMIN_EMAIL = "administrator@modulo-a-farfalla.local"
DESKTOP_USER_EMAIL = "desktop@modulo-a-farfalla.local"
TEXT = {
    "it": {
        "title": "Modulo a Farfalla",
        "starting": "Avvio in corso...", "ready": "Applicazione pronta", "open": "Apri applicazione",
        "data": "Apri cartella dati", "quit": "Arresta e chiudi", "close": "Arrestare l'applicazione? Le elaborazioni in corso verranno interrotte.",
        "error": "Impossibile avviare. Consulta logs/desktop.log nella cartella dati.",
        "busy": "Un'altra istanza sta avviando l'applicazione. Attendi e riprova.",
        "ai": "L'analisi IA non e' inclusa in questa distribuzione desktop. Tagging manuale ed esportazioni sono disponibili.",
    },
    "en": {
        "title": "Modulo a Farfalla",
        "starting": "Starting...", "ready": "Application ready", "open": "Open application",
        "data": "Open data folder", "quit": "Stop and close", "close": "Stop the application? Running jobs will be interrupted.",
        "error": "Unable to start. See logs/desktop.log in the data folder.",
        "busy": "Another instance is starting. Wait and try again.",
        "ai": "AI analysis is not included in this desktop distribution. Manual tagging and exports are available.",
    },
}


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def data_root() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "ModuloAFarfalla"
    override = os.environ.get("MODULO_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "modulo-a-farfalla"


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    temporary.replace(path)


class InstanceLock:
    def __init__(self, root: Path):
        self.stream = (root / "instance.lock").open("a+b")
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise RuntimeError("instance_locked") from None

    def close(self) -> None:
        self.stream.close()


def attach_windows_job():
    """Keep video subprocesses inside the application's lifetime."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("process_limit", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
    class IOCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops",
                                                      "read_bytes", "write_bytes", "other_bytes")]
    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", IOCounters), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                    ("peak_job_memory", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x2800  # Kill app children on exit; updater may explicitly break away.
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        if handle:
            kernel.CloseHandle(handle)
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise ctypes.WinError(ctypes.get_last_error())
    # Retain the handle until process exit; closing it earlier would kill this process.
    return handle


def load_config(root: Path) -> dict:
    path = root / "desktop.json"
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("version") != 1 or len(value.get("secret_key", "")) < 40:
            raise ValueError("Invalid desktop configuration; refusing to replace existing data")
        return value
    value = {"version": 1, "secret_key": secrets.token_urlsafe(48), "application_id": secrets.token_hex(16),
             "bootstrap_password": secrets.token_urlsafe(48), "initialized": False, "language": "it"}
    atomic_json(path, value)
    return value


def configure_environment(root: Path, config: dict) -> None:
    # Explicit values prevent inherited server settings from connecting to production.
    environment = {
        "DATABASE_URL": "sqlite:///" + (root / "touchline.db").as_posix(),
        "STORAGE_ROOT": str(root / "storage"), "SECRET_KEY": config["secret_key"],
        "BOOTSTRAP_ADMIN_EMAIL": ADMIN_EMAIL, "BOOTSTRAP_ADMIN_PASSWORD": config["bootstrap_password"],
        "COOKIE_SECURE": "false", "CORS_ORIGINS": "", "BACKGROUND_WORKERS": "1", "FFMPEG_THREADS": "2",
        "AI_ENABLED": "false", "AI_PYTHON": "", "AI_DEVICE": "cpu", "MEDIA_ACCELERATION": "auto", "FORCE_HARDWARE": "",
        "WORKER_NICE": "10", "MAX_UPLOAD_GB": "20",
    }
    os.environ.update(environment)
    binary_root = resource_root() / "ffmpeg"
    if binary_root.is_dir():
        os.environ["PATH"] = str(binary_root) + os.pathsep + os.environ.get("PATH", "")
        # The bundled FFmpeg resolves libva.so.2 at runtime; prefer the bundled
        # copy so VA-API keeps working on hosts with an older system libva.
        os.environ["LD_LIBRARY_PATH"] = str(binary_root) + (os.pathsep + os.environ["LD_LIBRARY_PATH"] if os.environ.get("LD_LIBRARY_PATH") else "")
    font_config = resource_root() / "fontconfig" / "fonts.conf"
    if font_config.is_file():
        # Static FFmpeg builds cannot resolve system fonts without an explicit
        # fontconfig file; the bundled one references the bundled DejaVu fonts
        # relative to itself, so it also works from a read-only mount.
        os.environ["FONTCONFIG_FILE"] = str(font_config)
    os.chdir(root)


def migrate_database(root: Path) -> None:
    from alembic import command
    from alembic.config import Config
    from app.db import engine, Base
    from app import models  # Ensure all current tables are registered before fresh bootstrap.
    database = root / "touchline.db"
    if database.exists():
        backup_dir = root / "database-backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / ("touchline-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3) + ".db")
        with sqlite3.connect(database) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Database backup verification failed; migration cancelled")
    configuration = Config()
    migration_root = resource_root() / "alembic"
    if not migration_root.is_dir():
        migration_root = resource_root() / "backend" / "alembic"
    configuration.set_main_option("script_location", str(migration_root))
    if database.exists():
        command.upgrade(configuration, "head")
    else:
        # Revision 0001 uses current metadata; 0005 then recreates league tables.
        # Only a genuinely new database may bootstrap the complete current schema.
        Base.metadata.create_all(engine)
        command.stamp(configuration, "head")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        if connection.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
            raise RuntimeError("Database integrity check failed")


def initialize_local_user(config: dict) -> str:
    """Ensure a local coach identity exists; the loopback client needs no login."""
    from app.db import SessionLocal
    from app.models import User, Role
    from app.security import hash_password
    from sqlalchemy import select
    email=(config.get("analyst_email") or DESKTOP_USER_EMAIL).strip().lower()
    with SessionLocal() as database:
        user=database.scalar(select(User).where(User.email==email))
        if user and user.role==Role.coach:
            return user.email
        user=database.scalar(select(User).where(User.role==Role.coach).order_by(User.created_at).limit(1))
        if user:
            return user.email
        email=DESKTOP_USER_EMAIL
        user=database.scalar(select(User).where(User.email==email))
        if user and user.role!=Role.coach:
            raise RuntimeError("The reserved local desktop account has an incompatible role")
        if not user:
            database.add(User(email=email,name="Local analyst",password_hash=hash_password(secrets.token_urlsafe(48)),role=Role.coach))
            database.commit()
    config.update(initialized=True,analyst_email=email)
    return email


def create_application(frontend: Path, application_id: str, origin: str, language: str = "it",
                       local_user_email: str = DESKTOP_USER_EMAIL,
                       shutdown=None, diagnostics=None):
    from app.main import app
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from starlette.staticfiles import StaticFiles
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_requests_only(request: Request, call_next):
        started = time.monotonic()
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") not in {None, origin} or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site request denied"}, status_code=403)
        if request.method == "POST" and request.url.path == "/api/ai/jobs":
            return JSONResponse({"detail": TEXT[language]["ai"]}, status_code=503)
        if request.method == "POST" and request.url.path == "/api/auth/login":
            return JSONResponse({"detail": "Login is not used by the local desktop edition"},status_code=404)
        response = await call_next(request)
        if diagnostics and request.url.path.startswith("/api/"):
            operation = "write" if request.method not in {"GET", "HEAD"} else "read"
            event = "api_failed" if response.status_code >= 500 else ("api_write" if operation == "write" else "api_request")
            diagnostics.event(event, operation=operation, status=response.status_code,
                              duration_ms=int((time.monotonic() - started) * 1000),
                              error_code="server" if response.status_code >= 500 else "unknown")
        from app.db import SessionLocal
        from app.models import User
        from app.security import make_token
        from sqlalchemy import select
        with SessionLocal() as database:
            local_user=database.scalar(select(User).where(User.email==local_user_email))
            if local_user:
                response.set_cookie("access_token",make_token(local_user),httponly=True,samesite="lax",
                                    secure=False,path="/",max_age=7*24*60*60)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/desktop/health", include_in_schema=False)
    def desktop_health():
        from app.media import hardware_backend
        if os.name == "nt":
            from app.windows_gpu import status
            video = status()
        else:
            video = {"selected": hardware_backend(), "playback": "browser_managed"}
        return {"application_id": application_id, "mode": "local", "workers": 1,
                "ai_bundled": False, "video": video}

    from desktop import update
    from desktop.diagnostics import PROFILES

    @app.get("/desktop/diagnostics/profile", include_in_schema=False)
    def diagnostics_profile():
        return {"profile": diagnostics.profile() if diagnostics else "production"}

    @app.put("/desktop/diagnostics/profile", include_in_schema=False)
    def diagnostics_set_profile(payload: dict):
        if not diagnostics or set(payload) != {"profile"} or payload["profile"] not in PROFILES:
            return JSONResponse({"detail": "Invalid diagnostics profile"}, status_code=422)
        diagnostics.set_profile(payload["profile"])
        return {"profile": diagnostics.profile()}

    @app.post("/desktop/diagnostics/export", include_in_schema=False)
    def diagnostics_export():
        from fastapi.responses import Response
        from desktop.update import build_version
        content = diagnostics.export(build_version()) if diagnostics else b""
        return Response(content, media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="modulo-a-farfalla-diagnostics.zip"',
            "Cache-Control": "no-store"})

    @app.post("/desktop/diagnostics/client-event", include_in_schema=False)
    def diagnostics_client_event(payload: dict):
        if set(payload) != {"event"} or payload["event"] not in {"client_failed", "client_action"}:
            return JSONResponse({"detail": "Invalid event"}, status_code=422)
        if diagnostics:
            diagnostics.event(payload["event"])
        return {"ok": True}

    @app.get("/desktop/update/check", include_in_schema=False)
    def update_check():
        try:
            release = update.public_release(update.latest_release())
            if diagnostics:
                diagnostics.event("update_check", operation="update")
            return release
        except update.UpdateError as exc:
            if diagnostics:
                diagnostics.event("update_failed", operation="update", error_code=exc.code)
            return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=503)

    @app.post("/desktop/update/install", include_in_schema=False)
    def install_update():
        if os.environ.get("MODULO_PACKAGER") in {"electron", "appimage"}:
            return JSONResponse({"detail": "Use the release link for this preview build", "code": "unsupported"},
                                status_code=503)
        try:
            installer = update.download_verified_update()
            update.start_update_helper(installer)
            if shutdown:
                threading.Thread(target=lambda: (time.sleep(0.7), shutdown()), daemon=True).start()
            return {"started": True}
        except (update.UpdateError, OSError, ValueError, KeyError, TypeError) as exc:
            detail = str(exc) if isinstance(exc, update.UpdateError) else "Update download or installation could not be prepared"
            code = exc.code if isinstance(exc, update.UpdateError) else "unexpected"
            if diagnostics:
                diagnostics.event("update_failed", operation="update", error_code=code)
            return JSONResponse({"detail": detail, "code": code}, status_code=503)

    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="desktop-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend_page(path: str):
        if path.startswith(("api/", "desktop/")):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (frontend / path).resolve()
        if candidate.is_relative_to(frontend.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend / "index.html")

    return app


def open_existing_instance(root: Path, config: dict, *, browse: bool = True) -> bool:
    import urllib.request
    try:
        state = json.loads((root / "instance.json").read_text(encoding="utf-8"))
        port = int(state["port"])
        if not 1024 <= port <= 65535:
            return False
        url = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(url + "/desktop/health", timeout=2) as response:
            health = json.load(response)
        if health.get("application_id") != config["application_id"]:
            return False
        if browse:
            webbrowser.open(url)
        return True
    except (OSError, ValueError, KeyError):
        return False


def open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)
    else:
        webbrowser.open(path.resolve().as_uri())


def run_server(root: Path, config: dict, *, headless: bool = False, ready_file: Path | None = None) -> None:
    import uvicorn
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    frontend = resource_root() / ("frontend" if getattr(sys, "frozen", False) else "frontend/dist")
    if not (frontend / "index.html").is_file():
        raise RuntimeError("Frontend build is missing")
    from desktop.diagnostics import Diagnostics
    diagnostics = Diagnostics(root)
    app = create_application(frontend, config["application_id"], origin, config["language"],
                             local_user_email=config.get("analyst_email",DESKTOP_USER_EMAIL),
                             shutdown=lambda: setattr(server, "should_exit", True), diagnostics=diagnostics)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, workers=1,
                                         proxy_headers=False, access_log=False, log_config=None))
    atomic_json(root / "instance.json", {"port": port})
    if headless:
        def signal_ready():
            while not server.started and not server.should_exit:
                time.sleep(0.1)
            if ready_file and server.started:
                atomic_json(ready_file, {"url": origin})
        threading.Thread(target=signal_ready, daemon=True).start()
        server.run(sockets=[sock])
        return
    import tkinter as tk
    from tkinter import ttk, messagebox
    text = TEXT[config["language"]]
    window = tk.Tk()
    window.title(text["title"])
    window.resizable(False, False)
    state = tk.StringVar(value=text["starting"])
    ttk.Label(window, textvariable=state, font=("Segoe UI", 12)).pack(padx=24, pady=16)
    def open_application():
        # Never block the GUI thread on the browser process: xdg-open can take
        # seconds to return and the user would see the button 'not open'.
        threading.Thread(target=webbrowser.open, args=(origin,), daemon=True).start()
    open_button = ttk.Button(window, text=text["open"], command=open_application, state="disabled")
    open_button.pack(padx=24, pady=6, fill="x")
    ttk.Button(window, text=text["data"], command=lambda: open_path(root)).pack(padx=24, pady=6, fill="x")
    ttk.Label(window, text=text["ai"], wraplength=400).pack(padx=24, pady=12)
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()

    def shutdown():
        if messagebox.askyesno(text["title"], text["close"]):
            server.should_exit = True
            state.set(text["quit"])
            finish()

    def finish():
        if thread.is_alive():
            window.after(250, finish)
        else:
            window.destroy()

    def wait_ready():
        if server.started:
            state.set(text["ready"])
            open_button.config(state="normal")
            open_application()
            window.after(250, monitor_server)
        elif not thread.is_alive():
            messagebox.showerror(text["title"], text["error"])
            window.destroy()
        else:
            window.after(250, wait_ready)

    def monitor_server():
        if thread.is_alive():
            window.after(250, monitor_server)
        else:
            window.destroy()

    ttk.Button(window, text=text["quit"], command=shutdown).pack(padx=24, pady=16, fill="x")
    window.protocol("WM_DELETE_WINDOW", shutdown)
    window.after(250, wait_ready)
    window.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="For automated smoke tests; remains loopback-only")
    parser.add_argument("--data-dir", type=Path, help="Isolated local data directory")
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args()
    root = (args.data_dir or data_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    (root / "logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler(root / "logs" / "desktop.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # GUI executables have no standard streams; libraries still expect writable ones.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    try:
        lock = InstanceLock(root)
    except RuntimeError:
        config = json.loads((root / "desktop.json").read_text(encoding="utf-8")) if (root / "desktop.json").exists() else {"language": "it", "application_id": ""}
        if open_existing_instance(root, config, browse=not args.headless):
            return 0
        if not args.headless:
            from tkinter import messagebox
            messagebox.showwarning(TEXT[config["language"]]["title"], TEXT[config["language"]]["busy"])
        return 2
    config = load_config(root)
    try:
        windows_job = attach_windows_job()
        configure_environment(root, config)
        migrate_database(root)
        local_user_email=initialize_local_user(config)
        config.update(initialized=True,analyst_email=local_user_email)
        atomic_json(root / "desktop.json",config)
        run_server(root, config, headless=args.headless, ready_file=args.ready_file)
        return 0
    except Exception:
        logging.exception("Desktop startup failed")
        if not args.headless:
            from tkinter import messagebox
            messagebox.showerror(TEXT[config["language"]]["title"], TEXT[config["language"]]["error"])
        return 1
    finally:
        (root / "instance.json").unlink(missing_ok=True)
        lock.close()


if __name__ == "__main__":
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    raise SystemExit(main())
