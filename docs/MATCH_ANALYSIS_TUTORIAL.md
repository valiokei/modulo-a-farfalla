# Match Analysis Tutorial

## Prepare the squad

Create each team and register players with shirt number and position. Use the
CSV import to add a roster in one operation. Keep names consistent between
matches so event statistics can be grouped correctly.

## Create a match

From **Matches**, choose **New match** and set date, home/away teams, season,
competition, venue and optional score. Select the team whose events you want to
analyse as the primary team. Attach the original video; additional camera
angles can be added later and aligned with a time offset.

## Tag the match

1. Open the match and wait for the video to become ready.
2. Play, pause or seek to the moment of interest.
3. Choose a category or its displayed keyboard shortcut. A tag records the
   event time against the selected video.
4. Add team, player/receiver, qualifiers, tags, notes and pitch coordinates in
   the event panel.
5. Review the event list and filters; edit or remove incorrect tags.

AI action spotting, when enabled on a supported Linux server, only proposes
reviewable suggestions. It does not create events until a coach explicitly
accepts or edits a suggestion. It is not included in the Windows desktop
installer, and its accuracy is not established for amateur footage.

## Notes, drawings and clips

Use **Notes and drawings** on the selected event to draw over the displayed
frame. Save the drawing before exporting. A single-event clip can hold a still
frame with saved screen drawings; unsupported tracked/field-anchored shapes are
reported rather than silently omitted. Keep the original video untouched and
inspect the exported clip before sharing.

## Statistics and exports

Match statistics are derived from saved event tags. Export event data as CSV or
JSON for downstream analysis. Clip/highlight export may take time; follow its
job status and download only after completion.

## Team and player CSV import

The import accepts UTF-8 CSV (a UTF-8 BOM is also supported) with a header row.
Required columns are `team_name` and `player_name`. Optional columns are
`season`, `shirt_number`, `position`, `player_notes`, and `team_notes`.

```csv
team_name,season,player_name,shirt_number,position,player_notes,team_notes
Example FC,2026/27,Ada Example,1,GK,,First team
Example FC,2026/27,Sam Example,8,CM,,First team
Example United,2026/27,Lee Example,10,FW,,
```

Repeated team names are grouped. Existing teams are matched case-insensitively;
existing players with the same normalized name and shirt number are skipped,
not overwritten. The import validates the whole file before writing and is
limited to 2,000 rows / 5 MiB. Download or prepare the template, then review
the result counts and any row errors before continuing.

## League data

Open **Leagues** to select an available competition and season, load provider
teams, import teams/rosters, then refresh fixtures/results. The integration
currently supports only a few competitions and public provider pages can
change. A clear provider-unavailable message is preferable to retrying rapidly;
do not use scraping to bypass access controls.
