# Third-party software and model notices

This is a starting inventory, not a complete substitute for the licence texts
distributed by each component. The project licence applies only to original
Modulo a Farfalla code and assets. It does not relicense these dependencies.

## Windows installer

The self-contained Windows build packages CPython, the backend runtime, the
locked frontend dependency tree, PyInstaller and FFmpeg/FFprobe. Their
copyright notices and licence texts must be retained in the installer output.
The current FFmpeg bundle is Gyan's FFmpeg 8.1.2 essentials static build and
includes GPL components. Build source and licence references:

- https://github.com/GyanD/codexffmpeg/releases/tag/8.1.2
- https://www.gyan.dev/ffmpeg/builds/
- https://ffmpeg.org/legal.html

The source archive checksum is checked by `desktop/build-windows.ps1`; the
script also copies the archive's licence/readme files into the bundled FFmpeg
directory. Verify those files and the applicable FFmpeg distribution duties
before each public binary release. A Modulo a Farfalla commercial licence does not
grant rights beyond the FFmpeg licence.

## Server AI

The optional Linux AI runtime uses OpenSportsLib and
`OpenSportsLab/OSL-loc-snbas-2025-e2e`. The model card declares AGPL-3.0:
https://huggingface.co/OpenSportsLab/OSL-loc-snbas-2025-e2e

The Windows installer does not include OpenSportsLib, Torch or model weights.
Server operators must review the exact upstream code, model and deployment
terms before enabling or redistributing the AI runtime. The project does not
grant commercial rights to those upstream components.

## Dependency inventory status

Backend direct dependencies are pinned in `backend/requirements.txt`; frontend
direct and transitive dependencies are locked in `frontend/package-lock.json`.
The source release includes machine-generated metadata in
`third-party/python-environment.json` and `third-party/npm-lock.json`; see
`third-party/README.md` for scope and regeneration. No third-party binaries or
model weights are included in this source repository.

Before publishing a Windows installer, regenerate the inventory for the actual
Windows build, retain bundled licence texts and provide the corresponding
source where required. CPython uses the PSF licence; PyInstaller uses GPL with
its bundling exception; Inno Setup has its own licence. Verify upstream notices
for the exact build versions. Do not infer that all dependencies use the project
licence or that this file alone establishes binary redistribution compliance.
