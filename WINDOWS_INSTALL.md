# Desktop installation (Windows · Linux)

Both desktop packages are self-contained single-user local clients. They do
not need Docker, Python, an account, or a connection to a Modulo a Farfalla
server. Download them from the
[official Releases page](https://github.com/valiokei/modulo-a-farfalla/releases/latest).
Releases are tagged with the app version (for example `v1.0.0`): the Windows
installer is `Modulo-a-Farfalla-Setup-<version>-x64.exe` and the Linux AppImage
is `Modulo-a-Farfalla-<version>-x86_64.AppImage`.

## Windows

1. Download the Windows x64 installer from the project's GitHub Releases.
2. Optionally compare its SHA-256 with the checksum published alongside it.
3. Run the installer and start **Modulo a Farfalla** from the Start menu.
4. The app opens its interface in your browser on a random `127.0.0.1` port.
   It is bound to this computer only and is not reachable from your LAN.
5. Your database, videos and settings stay in
   `%LOCALAPPDATA%\ModuloAFarfalla` after an update or uninstall. Back up this
   folder before installing a new version or moving to another PC.

Upgrades from an installer published **before v1.0.0** (old `windows-<date>-<sha>`
releases) cannot be detected by the old in-app updater, which refuses the new
`vX.Y.Z` tag format. Install the first `vX.Y.Z` release manually over the
existing installation once; later releases are detected normally in the app.

The client bundles FFmpeg and uses available NVIDIA, Intel or AMD video
encoders when detected, with CPU fallback. Playback decoding is controlled by
the browser and driver; GPU decoding is not guaranteed. AI action spotting is
not included in the Windows package.

Windows may warn that the installer is unsigned. Download it only from the
official project release page. Do not disable SmartScreen or antivirus.

## Linux (AppImage)

The same Releases page publishes a self-contained
`Modulo-a-Farfalla-<version>-x86_64.AppImage`, built and smoke-tested by CI on
every release. It needs no Docker, Python or account; all data stays in
`~/.local/share/modulo-a-farfalla`.

1. Download the AppImage and compare its SHA-256 with the published checksum.
2. `chmod +x Modulo-a-Farfalla-<version>-x86_64.AppImage`
3. Run it. The app opens its interface in your browser on a random `127.0.0.1`
   port, bound to this computer only.
4. To update, download the newer AppImage from the Releases page. The in-app
   update check detects new versions but the AppImage cannot install itself, so
   the update card links to the release page instead.

FFmpeg and the required runtime libraries are bundled with the AppImage.
AI action spotting is not included.

## First run

See the [Quick Start](docs/QUICKSTART.md) and
[match-analysis tutorial](docs/MATCH_ANALYSIS_TUTORIAL.md).
