# Dependency inventory

Generated on 2026-09-30 using `scripts/dependency-inventory.py`.

- `npm-lock.json` records every package entry in `frontend/package-lock.json`,
  including optional platform variants and development tools.
- `python-environment.json` records distributions installed from
  `backend/requirements.txt` in a clean Python 3.12 Linux environment. It
  preserves licence metadata and upstream project links as declared by each
  distribution. Windows dependency resolution may differ.

These files describe dependencies; this source repository does not vendor
their binaries or model weights. Upstream licences still apply independently
of the project's community licence. Build tooling and optional AI dependencies
have additional terms documented in `desktop/THIRD_PARTY_NOTICES.md`.

An installer release must carry the notices for its actual bundled versions
and satisfy source-distribution obligations where applicable. The inventory
is not a certification that a future binary package meets every obligation.

Regenerate in an isolated environment after dependency changes:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
python scripts/dependency-inventory.py
```
