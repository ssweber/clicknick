# The main window, the connection and CLICK's temp folder

Nothing loads this file automatically. The table in the root `AGENTS.md` says when to read it.

These notes cover `app.py`, `connection_controller.py`, `workspace_controller.py` and `connection_session.py`,
and CLICK's temp folder (`utils/click_temp.py`, `data/cdv_file.py`).

## Rules

- Never call `ClickNickApp._refresh_ui()` by hand. See "Main window refresh".
- The Dataview Editor and Verify use only the connected window's DataView folder (`click_dataview_folder`).
  They never use another `CLICK (*` folder.

## Main window refresh

- `ClickNickApp._refresh_ui()` recomputes the window title, the project name and the Workspace details. It
  also sets the Test group's legend and its Start/Stop label. It enables or disables Tools > Redraw Nicknames
  in CLICK and the system nickname entry of the Repairs menu. It updates the label and state of each Open
  Workspace menu entry (`WorkspaceController.refresh_menu_states`).
- Assigning `_data` or `_session` (`_ShownState` attributes) schedules one refresh for when Tk is idle.
  Requests made before it runs merge into it.
- These also call `_request_ui_refresh()`: the `ConnectionSession` events (sync count, analysis progress,
  staged rungs), the simulation's status and Modbus events, and Workspace setup when it pairs another
  workspace.
- `_refresh_ui` also re-titles the open editor windows, and it skips a window that is being destroyed. The
  windows take the project name and analysis as getters, so they follow a project change.

## Connection and lifecycle

- `ConnectionController` (`ClickNickApp._connection`) lists the CLICK windows, connects, follows a project change
  and runs the watch tick. It writes the session and the data only through the app (`_session`, `_open_data`,
  `_close_data`).
- `WorkspaceController` (`ClickNickApp._workspace`) runs the Workspace group, its menu entries and Workspace
  setup. It reads the session through the app each time.
- Connecting opens a `ConnectionSession` before CLICK's database loads. A project change replaces the session.
- `ConnectionController.close_session` is the one teardown. It drops the database load in flight, and it ends
  the watch, the popup, the Workspace setup window, the Simulator window, the simulation, the ScrWatcher and the
  analysis.
- Until ClickNick has read the database, the session builds nothing. `has_database` is False while the database
  loads and after the CSV fallback. In that time, the Workspace's **Review Changes**, **Reload from CLICK**, the
  simulation and applying Workspace setup refuse to run (`_project_session`). **Compare with > Folder** works
  without it.
- `no_database_reason` in `connection_session.py` says why a command cannot run. It tells the user to connect
  only when no window is connected. Otherwise it says that ClickNick is still reading the database
  (`reading_database`), that database access is off (`CLICKNICK_DB_BACKEND=none`), or to select the window
  again to load the database. In the last two cases, a command that needs only nicknames (`nicknames_needed`)
  also offers File > Load Nicknames from CSV. The status line (`_report_no_project_session`) and the commands
  that need the nicknames (`_report_no_data`) use it.
- `no_workspace_reason` says why a command that needs the workspace cannot run. Without the database, it
  returns the text of `no_database_reason`. Otherwise it says that the build failed, is running, or has not
  started. The app's commands use it.
- `clicknick-cli` gives the same reasons as the app, except while a build runs. Then it raises
  `WorkspaceBusyError`, the error that the workspace lock also raises. The live server reads the session through
  a getter (`get_session` on `DispatchContext`). A command that needs the addresses uses `no_database_reason`. A
  command that needs the workspace reports a failed build itself, and uses `no_workspace_reason` in every other
  case without a workspace.
- ClickNick drops a database load if its session closed, or if a CSV load or another connect cancelled it. It
  does this also when that happens during the prompt to save the data that the load replaces.
- While a CLICK window is connected, its session's watch (`_monitor_task`) checks every 100 ms whether the window
  closed or shows another project. The watch shows autocomplete popups while `monitoring` is on and data is
  loaded. The new project's session starts watching even when following the project fails part way.
- When the session opens, it pairs the durable workspace for the project's PLC name (`pair_workspace`). The
  Workspace setup window and its unapplied choice (`pending_workspace`) belong to the session. They close with
  it, when CLICK's window closes or shows another project.
- `monitoring` is the user's choice. It starts on. **Stop** turns it off, and only **Start** or a window that the
  user picks turns it on again. A project change, the CSV fallback and an automatic connect leave it as it was.
- When the window closes, database data closes without a prompt, and CSV data stays loaded. The app reads the
  CSV path (`_csv_path`) from the loaded CSV store.
- Refreshing the window list connects to the first window only when nothing is connected and no data is loaded.
  Otherwise the user picks. The list skips titles without a project. So ClickNick closes a connected window that
  is missing from the list only when its process is gone.
- The combobox always lists and selects the connected window, under the project that it shows
  (`_show_instances`).
- Closing ClickNick goes through `_close_data(prompt_save=True)`. Cancel or a failed save keeps ClickNick open.

### Another project in the same window

When the window shows another project, CSV data stays loaded. A Save As keeps the window's `CLICK (hwnd)`
folder, database and DataView folder, and so does opening another project. ClickNick cannot tell the two apart.
So it asks whether to keep the unsaved address and Dataview edits on database data for the new project
(`_keeps_edits_for`). Text in a cell that will not commit counts as an edit.

- If you keep them, the data and its windows stay open, the store's file monitor reads the new database, and
  Sync and the Dataview Save write there.
- If you do not, the database data closes with nothing saved, and the new database loads. A save after
  File > Open would overwrite the other project's .cdv files.
- Over CSV data, the question covers only Dataview edits, including text in a Dataview cell.
- A Dataview Editor that stays open lists its folder again when the edits were kept. Otherwise ClickNick closes
  it without saving and opens it again on the window's DataView folder (`_reopen_dataview_editor`).

## CLICK's temp folder

CLICK keeps each open project in a `CLICK ({hwnd:08X})` folder, one per window. The hwnd is the handle of
CLICK's window. ClickNick looks for that folder under the Windows temp folder (GetTempPathW), in its long form.
The root `AGENTS.md` has the rule that every lookup goes through `utils/click_temp.py`.

The Dataview model takes the folder as a getter (`_dataview_folder`). With no window connected, the getter
returns the loaded CSV's folder, or none.
