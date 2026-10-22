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

## On-demand AI runtime packs (Win64 and Linux x64)

The optional Windows "AI runtime" download (`ai-runtime-win64-1` prerelease)
and the Linux x64 one (`ai-runtime-linux-x64-1` prerelease), built by
`scripts/build-ai-pack.sh` and installed by `desktop/ai_runtime.py`,
redistribute, unmodified, the same components per platform:

- **CPython 3.12.15** (python-build-standalone, PSF licence) — its `LICENSE.txt`
  is included in the `python` component.
- **torch 2.14.0+cpu / torchvision 0.29.0+cpu** — Apache-2.0 with LLVM
  exception, BSD-2-Clause, BSD-3-Clause, BSL-1.0 and MIT components
  (per-wheel `License-Expression` metadata); licence files are included in
  each wheel's `dist-info/licenses/`. The Windows wheels are the `win_amd64`
  build and the Linux wheels the `manylinux` build of the same versions; the
  Linux tree is produced by `scripts/build-ai-linux-site-packages.sh`.
- **opensportslib 0.3.0.dev21** — **AGPL-3.0** (see `LICENSE` and
  `LICENSE-COMMERCIAL` in its `dist-info/licenses/`); a wheel of the pinned
  revision `4757f4f7f7b8b017cc5e84d58036e58a163e57b2`.
- **decord 0.6.0** (Apache-2.0) and its bundled FFmpeg shared libraries
  (`avcodec-58` etc., LGPL/GPL per FFmpeg build — the wheel ships its own
  copies); plus the other pinned wheels from the build script (opencv,
  transformers, pytorch-lightning, sklearn, …), each with its licence files
  retained in the extracted `site-packages`.
- **Model weights** `OpenSportsLab/OSL-loc-snbas-2025-e2e` (snapshot
  `54e24a663a5a0ed057ef12cf16d9460d270ddc6e`) — declared **AGPL-3.0** on its
  model card. The same cache is served to both platforms.

Redistributing this pack (or installing it inside another distribution) is
gated on the same human licensing review as the server AI. The pack stays a
**prerelease** so it is not offered as an application update; the desktop app
keeps AI off until the user installs it explicitly. Do not bundle the pack
into the installer or the AppImage without that review.

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

## Linux AppImage

The self-contained Linux AppImage packages CPython (PSF licence), the pinned
backend wheels, the built frontend, static FFmpeg/FFprobe from BtbN builds
(GPL), DejaVu fonts (Bitstream Vera licence with public-domain additions) and
libva 2.24 from Ubuntu (`libva2`, Expat licence) next to FFmpeg, because the
bundled FFmpeg resolves VA-API symbols from libva.so.2 at runtime and aborts
against older system libva versions. Archive checksums are pinned in
`scripts/build-appimage.sh`; licence texts ship beside each component
(`ffmpeg/LICENSE.txt`, `ffmpeg/libva-copyright.txt`,
`fontconfig/DejaVu-LICENSE.txt`).
