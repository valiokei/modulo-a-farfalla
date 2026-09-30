# Modulo a Farfalla Quick Start

This guide gets a new installation to its first match review with the fewest
required settings.

## Windows desktop

1. Install the x64 installer from the official project release.
2. Start **Modulo a Farfalla**. The desktop edition runs its API on loopback
   (`127.0.0.1`) and opens the local interface; it does not connect to a server
   or require an account.
3. Open **Squadre / Teams**, create the teams and add players, or import them
   from a CSV using the template described in [Team CSV import](MATCH_ANALYSIS_TUTORIAL.md#team-and-player-csv-import).
4. Create a match, select home and away teams, and add the match video.
5. Open the match and follow [Match analysis tutorial](MATCH_ANALYSIS_TUTORIAL.md).

Your Windows database and media stay under `%LOCALAPPDATA%\ModuloAFarfalla`.
Back up that folder before moving the installation to another PC.

## Linux / Docker server

1. Install Docker Engine and the Compose plugin on the intended host.
2. Clone the project and copy `.env.example` to `.env`.
3. Set unique values for `SECRET_KEY`, `POSTGRES_PASSWORD` and
   `BOOTSTRAP_ADMIN_PASSWORD`; do not expose the example defaults.
4. Start the stack with `docker compose up --build -d`.
5. Open `http://localhost:8080`, sign in with the bootstrap admin credentials,
   and immediately create a personal admin password if the deployment policy
   requires it.
6. Create teams and players (or import a CSV), then create a match and upload
   its video.

For remote use, configure HTTPS, backups, firewalling and secure cookies before
opening access beyond a trusted LAN. See the deployment section in the README.

## First review checklist

- Confirm the match date, teams, season and competition.
- Let the proxy/transcode job finish before reviewing.
- Seek to an event and tag it with a category; use keyboard shortcuts shown by
  the category controls.
- Add a note, participants, qualifiers and pitch location where useful.
- Save telestration before exporting a clip.
- Review exports before sharing them. Original uploads are not overwritten.

The supported public league import currently covers only a small set of
competitions from FAČR–PFS and PIBFAL. Availability and completeness depend on
those public providers; manual team and match entry remains available.
