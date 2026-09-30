# Windows Installation

Modulo a Farfalla for Windows is a self-contained, single-user local client.
It does not need Docker, Python, an account, or a connection to a Modulo a
Farfalla server.

Public installer release status: preparation in progress. The new public
repository does not yet publish a verified installer. Follow the
[official Releases page](https://github.com/valiokei/modulo-a-farfalla/releases)
for the first download; source code availability is not an installer release.

1. Download the Windows x64 installer from the project's GitHub Releases.
2. Optionally compare its SHA-256 with the checksum published alongside it.
3. Run the installer and start **Modulo a Farfalla** from the Start menu.
4. The app opens its interface in your browser on a random `127.0.0.1` port.
   It is bound to this computer only and is not reachable from your LAN.
5. Your database, videos and settings are stored under
   `%LOCALAPPDATA%\ModuloAFarfalla`. Back up this folder before moving to a
   different PC or uninstalling.

The client bundles FFmpeg and uses available NVIDIA, Intel or AMD video
encoders when detected, with CPU fallback. Playback decoding is controlled by
the browser and driver; GPU decoding is not guaranteed. AI action spotting is
not included in the Windows package.

Windows may warn that the installer is unsigned. Download it only from the
official project release page. Do not disable SmartScreen or antivirus.

See the [Quick Start](docs/QUICKSTART.md) and
[match-analysis tutorial](docs/MATCH_ANALYSIS_TUTORIAL.md) for the first run.
