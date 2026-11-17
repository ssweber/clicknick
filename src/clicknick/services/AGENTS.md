# Program analysis, backups and the workspace lock

These notes cover the analysis build (`connection_session.py`, `services/analysis_service.py`,
`services/scr_watcher.py`, `services/tag_names.py`), the backups of `src/plc`
(`services/project_workspace.py`, `services/workspace_mirror.py`) and the workspace lock. The services in this
folder never import tkinter (rule 3 in the root `AGENTS.md`). Other services have their notes elsewhere. The
table at the end of the root `AGENTS.md` names the file for each one.

The workspace is the pyrung project that ClickNick generates from the connected CLICK project. Its folders
include `csv/` and `src/plc`. A build reads CLICK's program from its Scr*.tmp files and the nicknames from its
database, and generates the workspace again.

## Builds

- One build worker runs per connection. Requests made while it runs collapse into one follow-up build.
  `ConnectionSession.start_analysis` queues no build while one runs, because that build serves the request.
  It makes the ScrWatcher once per session. The ScrWatcher counts the addresses synced into CLICK's database
  since CLICK last saved. It also holds the count of staged rungs.
- When a build finishes, it replaces `csv/` and `src/plc` as a pair and records the generation last. So a
  workspace never holds `csv/` from one save and `src/plc` from another.
- If a build fails before it replaces them, `project_dir` stays at an earlier save (`project_is_current` is
  False). Review Changes then has nothing to compare with.
- `SavedProgram.save_count` is the one signal that CLICK saved. Only the ScrWatcher raises it, once per save.
  The ScrWatcher checks the Scr*.tmp files every 3 s (`SCR_WATCH_INTERVAL_MS`). After it sees a change, it
  checks every 500 ms (`SCR_SETTLE_MS`). It counts a save once two checks in a row (`SCR_QUIET_CHECKS`) find
  the files unchanged. A Sync rebuild, Reload from CLICK, a workspace change, a retry and a failed build leave
  the count as it was.
- `AnalysisService.status` reads BUILDING until a build finishes that serves every request made so far.
  `mark_building` returns the count of requests, and `build(serves=)` takes it. Suppose a build of the files
  from before a save finishes while the save's build is queued. The status stays BUILDING. So no reader pairs
  a new save with the `csv/` of the save before. The readers are `saved_program()`, `rung apply`, the
  Workspace status and the simulation.
- Suppose a request fails before it is queued while a build runs. That is `mark_failed` without `serves`, as
  when there is no database or no Scr*.tmp file. The status stays BUILDING. The failure shows once the build
  that serves every request finishes, unless a later request replaced it.
- The generated code, the project that the build writes and the tag map all come from one nickname snapshot
  that the build reads from CLICK's database. The tag names are the ones that pyrung's own reader gives for
  that snapshot's `nicknames.csv` (`services/tag_names.py`). So they match the code, whatever pyrung does with
  spaces. ClickNick's edits reach the analysis on the next build after a Sync.
- `clicknick-cli` finds tags by the workspace's names (`project_tag_to_addr_key`).
- `csv/analog_inputs.json` records the analog inputs that a workspace was generated with. `tag apply`
  regenerates its baseline `tags.py` from them, never from CLICK's Project.ini at the time it runs.

## Backups of src/plc

- `backup/src/plc` is the newest backup of `src/plc`. ClickNick takes a backup before a build replaces edited
  source, on `clicknick-cli backup`, and when the user keeps a chosen workspace's edits.
- Each new backup first moves the current one to `backup/older/<YYYYMMDDTHHMMSSZ>/src/plc`. The folder is
  named in UTC by the time that the backup was taken (`backup/backup-time.txt`). When that file cannot be
  written, the backup's files are dated to that time instead.
- If any kept backup already holds the tree, ClickNick makes no new backup, and that backup becomes the newest.
- ClickNick deletes the oldest backups so that 5 are kept in all (`KEPT_PLC_BACKUPS`). It renames each one out
  of the listing before it deletes it. It deletes only once the whole backup or restore succeeded. If one
  fails, `src/plc` stays as it was and no backup is deleted. Nothing refuses a save or a backup because of
  this.
- `clicknick-cli restore` takes the newest backup, and `restore <time>` takes an older one. It copies the chosen
  backup aside. Then it backs up `src/plc` if that differs from both the last generation and the chosen
  backup, and it replaces `src/plc`. Its pruning keeps the restored backup, so six may be kept until the next
  backup.
- A build, backup or restore that succeeds leaves the edits that `src/plc` held as the newest backup. A
  restore leaves them in `src/plc`, as the backup that it restored. A tree that was once in a backup, or that
  was in `src/plc` with edits when a build, backup or restore began, can be deleted only after 5 newer backups
  are kept. `tests/AGENTS.md` names the test that checks these rules.

## The workspace lock

Each workspace folder has one lock (`workspace_writing`). A build holds it from its backup of edits to the
generation record. `backup`, `restore` and choosing a workspace hold it throughout. The build waits for the
lock. The others run on the Tk thread, so ClickNick refuses them (`WorkspaceBusyError`) and the window does
not freeze. ClickNick refuses the `clicknick-cli` commands that read the workspace the same way while the
analysis is BUILDING (`_get_project_dir`).
