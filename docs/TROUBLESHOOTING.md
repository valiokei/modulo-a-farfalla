# Diagnostics and league imports

## Windows diagnostics

Open **Diagnostica** above the workspace. Choose one of three levels:

| Level | Records | Use |
| --- | --- | --- |
| Production (default) | Failures only | Normal use |
| Simple | Failures and completed actions | Reproduce a workflow issue |
| Detailed | Request timing and technical categories | Short troubleshooting session |

Click **Esporta diagnostica** to save a ZIP. It contains only allowlisted event
types, status codes and durations; it does not contain videos, database rows,
player names, credentials or the raw application log. Logs rotate at about
3 MB total. Return to **Production** after troubleshooting. Review the archive
before sharing it, as with any diagnostic file.

If the updater fails, its message distinguishes DNS, TLS/certificates, proxy,
timeout, HTTP, invalid release metadata and missing release assets. **Riprova**
checks again; **Release** opens the canonical GitHub releases page. A browser
opening `github.com` does not prove that the desktop process can reach
`api.github.com`. Do not disable TLS verification or install an unverified EXE.

## PFS roster import

1. In **Squadre → Importa campionato**, select the season and load competitions.
2. Choose the exact competition and load teams.
3. For clubs entered in multiple groups, select the intended *local* team for
   each group. Old unscoped mappings are marked for manual review; the app does
   not trust them automatically.
4. Select a team under **Anteprima rosa**. Compare the official players with
   the selected local team before importing.
5. Back up the database, then use **Importa con rose**. Repeating the same
   import is idempotent. No existing local player is deleted automatically.

The official site may identify several teams with the same club ID; the
competition and season are therefore part of the mapping and roster request.
If a local roster already contains players from the wrong group, the preview
lists them as *only on local team*. Review match references and correct those
players manually after a verified backup; importing does not erase history.

For Docker/PostgreSQL, make a consistent `pg_dump` before a correction; for
Windows, close the app and copy `%LOCALAPPDATA%\ModuloAFarfalla` to a separate
location. Do not use the old club-specific seed script for repair.
