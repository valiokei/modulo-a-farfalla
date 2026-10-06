# Modulo a Farfalla

**Football belongs to everyone. The tools that help people understand the game
should not cost grassroots clubs thousands of euros.**

Support: [PayPal](https://www.paypal.com/donate?hosted_button_id=AF72GDATCBQ7S) | [Revolut](https://revolut.me/valerixu32)

Modulo a Farfalla is a football video-analysis workspace for coaches and
players. It brings match video, event tagging, notes, clips, team records and
reviewable AI suggestions together, while keeping the club in control of its
data.

The community licence is source-available, not OSI-approved, and permits
personal, educational and grassroots amateur-club use. Professional,
commercial, paid-academy, hosted-service and resale use requires a separate
written commercial licence. Third-party components remain under their own terms.

## What it can do

| Capability | Desktop app (Windows / Linux) | Self-hosted server (Docker) | Notes |
| --- | --- | --- | --- |
| Match and multi-camera video review | Available | Available | Local desktop data is separate from any server deployment. |
| Manual event tagging, qualifiers, participants and pitch coordinates | Available | Available | Configurable event taxonomy and templates. |
| Notes, drawings, clips and highlights | Available | Available | Supported screen annotations can be burned into exported clips; unsupported tracking-anchored shapes fail explicitly. |
| Team, player and match administration | Available | Available | Admin, coach and read-only player roles on the server. |
| League data import | Available, requires Internet | Available, requires Internet | Only a small set of competitions is supported; public FAČR–PFS and PIBFAL pages may change. |
| Video encoding acceleration | NVIDIA, Intel and AMD paths implemented | NVIDIA or VA-API Intel/AMD overlays | Actual hardware support depends on GPU, drivers, FFmpeg build and input. Verify on the target machine. |
| Browser video playback acceleration | Browser-managed | Browser-managed | The app cannot force hardware decoding; browser and driver determine it. |
| AI action spotting | Not included | Optional Linux runtime | Suggestions only; a coach must review and accept them. Accuracy on amateur footage is not established. |
| Player tracking and automatic tactical metrics | Not available | Not available | APIs/data structures are groundwork, not a functioning tracker. |

### Compatibility

| Environment | Status | Requirements / limits |
| --- | --- | --- |
| Windows 10 x64 (build 19041+) and Windows 11 x64 | Supported desktop installer | Current vendor graphics drivers recommended; no Docker, Python or separate FFmpeg install required. ARM and 32-bit Windows are not packaged. |
| Linux x86_64 (AppImage) | Supported desktop download | Self-contained; no Docker, Python or separate FFmpeg install required. Built and smoke-tested by CI on every release; verify playback and encoding on the intended hardware. |
| Linux x86_64 with Docker Compose | Supported self-hosted deployment | Docker Engine/Compose and persistent storage; optional GPU overlay must match the host runtime. |
| macOS, Windows ARM | Not currently packaged or acceptance-tested | Use the documented development/server path only where dependencies are supported. |
| AI on the desktop app | Not available | Torch, OpenSportsLib and model weights are not bundled. |

GPU support describes implemented selection and fallback paths, not a promise
that every device has been physically tested. The hosted Windows and Linux
builds run on GPU-less runners; test import/export and playback on the
intended hardware.

## Server and client

Modulo a Farfalla is a client–server application. The **server** (Python /
FastAPI) owns the database, the media files and the background video jobs
(proxy creation, clip and highlight exports). The **client** is a web
interface (React SPA) opened in a browser. In the desktop app the server
serves the interface directly; in the Docker deployment a small web container
serves it and forwards API calls to the server. Either way there is no
separate client program to install. It runs in two supported ways:

| | Desktop app (Windows / Linux) | Self-hosted server (Docker) |
| --- | --- | --- |
| How it runs | The app starts a private server on `127.0.0.1` (a free local port) and opens the interface in your browser. | The server runs on a host you manage and serves browsers on your network. |
| Access | Loopback only: not reachable from other devices. No login; a local coach profile. | Login with admin, coach or player accounts (a bootstrap admin is created on first start). |
| Data | Your user folder: `%LOCALAPPDATA%\ModuloAFarfalla` (Windows) or `~/.local/share/modulo-a-farfalla` (Linux). | PostgreSQL plus persistent media volumes on the host. |
| AI action spotting | Not included. | Optional runtime; suggestions only, reviewed by a coach. |

Desktop data is separate from any server deployment: each keeps its own
database and media.

## The interface

The web interface is a single workspace with three main areas:

- **Library** — the starting screen. **Matches** lists your matches (create
  one, then add one video per camera); **Teams** manages teams and rosters,
  with a roster CSV import; **Leagues** browses official competitions,
  fixtures and standings, imports league data and results (with explicit
  team mapping), and opens a fixture directly for analysis.
- **Match analysis** — the review and tagging view: camera switching,
  playback controls (play/pause, ±10 s, frame stepping, speed, fullscreen,
  loop) and a timeline with one marker per event plus category filters.
  - Tag events as the video plays, using per-category keyboard shortcuts
    (shown on each category button); each event keeps team, participants,
    qualifiers, notes, tags and an optional pitch position.
  - Every event has a **time window** (editable from/to): the loop flag
    repeats exactly that window, and clip export uses it.
  - **Notes and drawings**: pause on a frame and draw with pen, polygon or
    arrow, in five colours, with undo/redo. Drawings are saved per event,
    replay during playback and can be burned into exported clips.
  - **Stats**: coach metrics in groups, each drillable back into the video,
    and a pitch map of tagged positions.
  - **Exports**: event clip with overlays and an optional freeze-frame
    pause, compiled match highlight, and CSV/JSON of the tagged events.
- **Role screens** — server deployments add an **admin console** for user
  accounts and a read-only **player portal** with personal stats and matches.

The interface is Italian by default; a flag button switches between
Italian and English. The desktop app additionally shows a status bar with the
detected video encoder, the browser's playback capability estimate, the update
check and a diagnostics export.

## Windows and Linux desktop

For updater errors and league roster checks, see
[Diagnostics and league imports](docs/TROUBLESHOOTING.md).

Download the [Windows installer](https://github.com/valiokei/modulo-a-farfalla/releases/latest)
or the [Linux AppImage](https://github.com/valiokei/modulo-a-farfalla/releases/latest).
They run locally, need no login, and preserve your data when updated.
Releases are tagged with the app version (`v1.0.0`) and carry both packages
with their SHA-256 checksums: the Windows installer
(`Modulo-a-Farfalla-Setup-<version>-x64.exe`) and the Linux AppImage
(`Modulo-a-Farfalla-<version>-x86_64.AppImage`).

New releases are published from tested commits on `main`. See the
[Quick Start](docs/QUICKSTART.md), [match-analysis tutorial](docs/MATCH_ANALYSIS_TUTORIAL.md)
and [installation guide](WINDOWS_INSTALL.md).

## Self-host with Docker

```bash
cp .env.example .env
# Set unique SECRET_KEY, POSTGRES_PASSWORD and BOOTSTRAP_ADMIN_PASSWORD values.
docker compose up --build -d
```

Open `http://localhost:8080`. For a persistent deployment, configure `.env`
and run `./scripts/deploy.sh`. The database is not published as a host port;
media is kept in persistent volumes. Back up both the database and media.

Optional video-encoding overlays:

```bash
# Intel or AMD VA-API
docker compose -f docker-compose.yml -f docker-compose.vaapi.yml up --build -d

# NVIDIA with a compatible NVIDIA Container Toolkit
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
```

Put a self-hosted deployment behind a correctly configured HTTPS reverse proxy
before allowing access beyond a trusted local network. Set `COOKIE_SECURE=true`,
restrict CORS to the actual browser origin, replace bootstrap credentials, and
keep the host and dependencies updated.

## Development

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# In another terminal
cd frontend
npm install
npm run dev
```

The API docs are at `http://localhost:8000/docs`. Run backend tests with
`cd backend && python -m pytest -q`, and build/type-check the SPA with
`cd frontend && npm run build`.

## AI use and transparency

AI-assisted tools were used during development of this software, including
support for coding, debugging and documentation. The maintainer reviewed and
tested changes, but AI assistance can still introduce defects; report issues
with reproducible steps. This development use is separate from the optional
AI feature described below.

AI action spotting is optional and currently available only in the Linux/server
runtime, not in the desktop app (Windows or Linux). It uses OpenSportsLib's
`LocalizationModel` with the `OpenSportsLab/OSL-loc-snbas-2025-e2e` model. The
model card declares AGPL-3.0; OpenSportsLib and model terms must be reviewed
separately before deployment or redistribution. The project does not relicense
those components.

Predictions are stored as reviewable suggestions, never silently turned into
match events. A coach must accept, edit or reject them. Useful accuracy,
precision and recall have **not** been established. No automatic player
tracking, team attribution or tactical-metric generation is claimed.

## Licensing

The project aims to make capable analysis tools accessible to grassroots
football. The [LICENSE](LICENSE) allows the stated non-commercial community
uses. Commercial use would need a
separate written agreement with the maintainer; contact
Valerio Brunacci through [GitHub](https://github.com/valiokei). No commercial
price is implied by this repository. Contributions and third-party dependencies
have separate rights; see [CONTRIBUTING](CONTRIBUTING.md) and
[third-party notices](desktop/THIRD_PARTY_NOTICES.md).

## Current release status

The Windows installer is unsigned; Windows SmartScreen may show a warning.
Neither package is code-signed. Get the installer or the AppImage only from the
project's verified GitHub Releases and compare the published SHA-256. Do not
disable SmartScreen or antivirus globally. Server deployments are self-hosted
and require the operator to secure backups, authentication, TLS and network
access.
