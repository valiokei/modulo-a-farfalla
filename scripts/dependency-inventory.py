"""Generate dependency metadata; run in a clean backend virtualenv."""
import importlib.metadata
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
out = root / "third-party"
out.mkdir(exist_ok=True)
python_packages = []
for dist in importlib.metadata.distributions():
    if not Path(dist.locate_file("")).resolve().is_relative_to(Path(sys.prefix).resolve()):
        continue
    meta = dist.metadata
    python_packages.append({
        "name": meta["Name"], "version": meta["Version"],
        "license_expression": meta.get("License-Expression"),
        "license_metadata": meta.get("License"),
        "license_classifiers": [c for c in meta.get_all("Classifier", []) if c.startswith("License ::")],
        "project_urls": meta.get_all("Project-URL", []),
    })
python_packages.sort(key=lambda p: p["name"].lower())
lock = json.loads((root / "frontend/package-lock.json").read_text())
npm_packages = [{"path": path, "version": p.get("version"),
                 "license": p.get("license"), "dev": p.get("dev", False),
                 "optional": p.get("optional", False)}
                for path, p in sorted(lock["packages"].items()) if path]
for name, data in [("python-environment.json", python_packages), ("npm-lock.json", npm_packages)]:
    (out / name).write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n")
print(f"Inventoried {len(python_packages)} Python and {len(npm_packages)} npm packages")
