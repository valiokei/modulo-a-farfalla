"""Privacy-preserving desktop diagnostics; event fields are allowlisted."""
from __future__ import annotations

import io
import json
import logging
from logging.handlers import RotatingFileHandler
import platform
from pathlib import Path
import time
import zipfile

PROFILES = {"production": 0, "simple": 1, "diagnostic": 2}
EVENTS = {
    "startup_failed": 0, "update_failed": 0, "api_failed": 0, "client_failed": 0,
    "update_check": 1, "api_write": 1, "client_action": 1,
    "api_request": 2, "update_request": 2,
}
FIELDS = {"status", "duration_ms", "error_code", "operation"}
OPERATIONS = {"update", "import", "export", "upload", "read", "write", "other"}


class Diagnostics:
    def __init__(self, root: Path):
        self.root = root
        self.config = root / "diagnostics.json"
        (root / "logs").mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(f"desktop.diagnostics.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        handler = RotatingFileHandler(root / "logs" / "diagnostics.jsonl", maxBytes=1_000_000,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)

    def profile(self) -> str:
        try:
            value = json.loads(self.config.read_text(encoding="utf-8"))
            return value["profile"] if value["profile"] in PROFILES else "production"
        except (OSError, ValueError, KeyError, TypeError):
            return "production"

    def set_profile(self, profile: str) -> None:
        if profile not in PROFILES:
            raise ValueError("Invalid diagnostics profile")
        temporary = self.config.with_suffix(".tmp")
        temporary.write_text(json.dumps({"profile": profile}), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self.config)
        self.event("client_action", operation="other")

    def event(self, event: str, **values: object) -> None:
        if event not in EVENTS or EVENTS[event] > PROFILES[self.profile()]:
            return
        entry: dict[str, object] = {"timestamp": int(time.time()), "event": event}
        for key, value in values.items():
            if key not in FIELDS:
                continue
            if key in {"status", "duration_ms"} and type(value) is int:
                entry[key] = max(0, min(value, 600_000))
            elif key == "operation" and value in OPERATIONS:
                entry[key] = value
            elif key == "error_code" and isinstance(value, str) and value in {
                "dns", "tls", "proxy", "timeout", "network", "http", "metadata", "asset",
                "unexpected", "server", "client", "unknown"
            }:
                entry[key] = value
        self.logger.info(json.dumps(entry, sort_keys=True, separators=(",", ":")))

    def export(self, version: str) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
            manifest = {"profile": self.profile(), "platform": platform.system(),
                        "python": platform.python_version(), "build": version}
            bundle.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
            for suffix in (".2", ".1", ""):
                path = self.root / "logs" / f"diagnostics.jsonl{suffix}"
                if path.is_file():
                    bundle.write(path, f"diagnostics{suffix}.jsonl")
        return stream.getvalue()
