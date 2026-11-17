# ClickNick Agent Guidance

**IMPORTANT: Do not use `cd` before commands. The working directory is already the project root.**
**IMPORTANT: Use `make` to install, lint, test and build. While the sibling checkouts are installed (`make install-dev`), run `make lint UV_NO_SYNC=1` and `make test UV_NO_SYNC=1`, and never a bare `make` or `make install`. Those re-sync and put the released packages back.**

## Writing

Prose in this repo follows the `writing` skill in the bob plugin (`/bob:writing`, or `skills/writing/SKILL.md` in https://github.com/ssweber/bob). Read it before you write a commit message, a changelog entry, docs, a docstring, a comment, a message or UI text. The rules below are only the ones specific to this repo.

- The Unreleased section of `CHANGELOG.md` moves with what a user sees, in every pull request. Docs (`docs/`, `docs/help/`) change only where what a user does changes.

## Rules

- Run the tests with `make test`. Never run `uv run pytest` directly.
- Everything that looks for SC_.mdb, Address.csv, Project.ini, Scr*.tmp or the DataView folder goes through
  `utils/click_temp.py` (`click_temp_dir`), from the connected window's hwnd.
- Views never own a `DapService`.
- Never call `ClickNickApp._refresh_ui()` by hand. `src/clicknick/CONNECTION.md` says what refreshes the main
  window.
- Before you change code in a folder, read the files that the table at the end of this file names for it.

`tests/test_store_boundaries.py` enforces rules 2, 3 and 5. For rule 5 it checks that nothing outside the store
touches `_current_session`.

1. **Models are immutable.** `AddressRow` is `frozen=True`. Every change creates a new instance
   (`dataclasses.replace()`).
2. **AddressStore is the gatekeeper.** Only `AddressStore` writes its layers (`base_state`, `user_overrides`,
   `visible_state`, `block_colors`, `row_order`).
3. **Services and data are pure logic.** `services/`, `data/` and `simulation_session.py` never import
   `tkinter`.
4. **Views are passive.** Views look up rows through `store.visible_state[addr_key]` and listen for change
   notifications. Nothing keeps a row reference across a change.
5. **Every edit goes through `store.edit_session()`.** Write through the session that it yields. Never touch
   `store._current_session`.
6. **One home per fact.** The current data lives in `ClickNickApp._data` (a `DataSession`). The connected CLICK
   window lives in `ClickNickApp._session` (a `ConnectionSession`). The session holds its `click` (an immutable
   `ClickConnection`), its workspace `pairing`, the connection watch, the autocomplete popup and the Workspace
   setup window. `ClickNickApp._click` reads it. Consumers receive getters, not copies.
7. **No compatibility shims.** When an API changes, update its callers. Do not keep aliases or wrappers.

## Project overview

ClickNick is a Windows desktop application for Windows 10 and 11. It needs Python 3.13 or 3.14. It adds
nickname autocomplete and editing tools to the CLICK PLC Programming Software (v2.60–v4.00). It reads and writes
nicknames in the project's Access database (SC_.mdb) through Access ODBC or the built-in Windows Jet fallback.
It can also load nicknames from a CSV file (File > Load Nicknames from CSV) and save them back to that file. The
Address Editor's File > Import from CSV merges a CSV into the loaded data.

- **Overlay** positions a combobox over the edit controls of CLICK's instruction dialogs, for nickname
  autocomplete.
- **Address Editor** is a tabbed tksheet editor with search and replace, block tagging and validation. Each tab
  shows all memory types in one scrollable view.
- **Tag Browser** is a tree view of the nicknames, split at underscores and array indices.
- **Dataview Editor** edits .cdv files and looks nicknames up in the shared address data.
- **Review Changes** steps ladder from a folder of CSVs into CLICK.
- **Simulator** runs the workspace's program in pyrung, with an I/O panel and a command console. The workspace
  is the pyrung project that ClickNick generates from the connected CLICK project.

## Commands

```bash
make install                    # uv sync --locked --all-extras --dev
make                            # install, lint and test
make lint                       # ruff check --fix, then ruff format (devtools/lint.py)
make test                       # uv run pytest --quiet --tb=short
make build                      # uv build: the sdist and the wheel, into dist/
uv run clicknick                # run the app
uv tool install --editable .    # install as an editable local tool
```

`UV_NO_SYNC=1` keeps `uv run` from syncing the environment to `uv.lock` first. Without it, the `uv run` inside
`make lint` and `make test` syncs and puts the released pyclickplc, pyrung and laddercodec back in place of the
sibling checkouts. `uv run clicknick` re-syncs the same way unless `UV_NO_SYNC=1` is set.

`make lint` changes files. It runs `devtools/lint.py` on `src`, `tests` and `devtools`. `devtools/lint.py
--check` runs the read-only forms (`ruff check`, `ruff format --check`).

## Entry points

- `clicknick` (GUI) calls `clicknick:main`. The main app is `ClickNickApp` in `src/clicknick/app.py`.
- `clicknick-cli` calls `clicknick.live.cli:main`.
- `clicknick-rung` calls `clicknick.ladder.cli:main` (see `src/clicknick/ladder/AGENTS.md`).

## Package map

```
src/clicknick/
├── app.py                 # Main ClickNickApp class
├── config.py              # AppSettings: autocomplete and Redraw Ladder on Sync, as tkinter variables (not saved)
├── data_session.py        # DataSession: current store + Dataview model + editor windows
├── connection_session.py  # ClickConnection + ConnectionSession (watch, workspace, analysis, simulation)
├── connection_controller.py  # ConnectionController: window list, connect, project change, watch tick
├── simulation_session.py  # SimulationSession: pyrung DAP + Modbus + simulator settings (no tkinter)
├── workspace_controller.py  # WorkspaceController: the Workspace group, its menu entries, Workspace setup
├── models/                # Data models and constants
│   ├── address_row.py     # Frozen dataclass for address data
│   └── mutable_row_builder.py  # Builder for accumulating changes
├── data/                  # Data storage and state management (no tkinter)
│   ├── address_store.py   # Core store: base/overlay/visible layers, undo/redo, _derive
│   ├── edit_session.py    # Builder-backed session yielded by store.edit_session()
│   ├── cdv_file.py        # DataView folder discovery and CDV verification
│   └── undo_frame.py      # Undo/redo snapshot storage
├── services/              # Business logic (pure Python, no tkinter)
├── utils/                 # Utilities (filters, MDB, Win32)
├── ladder/                # Clipboard I/O, the clicknick-rung CLI, and program.py (the ladder program code
│                          #   that the app and the services share)
├── live/                  # clicknick-cli and the server it talks to in the app
├── views/                 # Windows and panels (passive observers)
│   ├── address_editor/    # Address Editor views
│   ├── dataview_editor/   # Dataview Editor views
│   └── nav_window/        # Tag Browser (outline, blocks)
├── widgets/               # Reusable UI components
├── detection/             # Window detection for Click.exe
└── resources/             # Icons and static assets
```

## Key dependencies

The runtime dependencies are `laddercodec`, `pyclickplc`, `pyrung`, `pywin32`, `pyodbc` and `tksheet` v7
(https://ragardner.github.io/tksheet/DOCUMENTATION.md). `pyproject.toml` pins each one exactly. It also pins four
transitive packages, `pymodbus`, `executing`, `pyrsistent` and `tomlkit`, so that a fresh install matches
`uv.lock`. `tkinter` comes from the standard library.

## Where to read next

Each subsystem has its notes in one file. This table lists that file under every folder that the subsystem
touches.

| Before you change code in | Read |
|---|---|
| `src/clicknick/` (the files at the top) | `src/clicknick/CONNECTION.md` for every file except `simulation_session.py` (the main window and the connection). `src/clicknick/SIMULATION.md` for `simulation_session.py`, `app.py` and `connection_session.py` (the simulation, and what starts and stops it). `src/clicknick/services/AGENTS.md` for `connection_session.py` (analysis builds). `src/clicknick/data/AGENTS.md` for `connection_controller.py` (the redraw after a Sync). |
| `src/clicknick/data/`, `src/clicknick/models/` | `src/clicknick/data/AGENTS.md`. For `data/cdv_file.py`, also `src/clicknick/CONNECTION.md` (CLICK's temp folder). |
| `src/clicknick/services/` | `src/clicknick/services/AGENTS.md` (analysis, backups, the workspace lock). `src/clicknick/data/AGENTS.md` for `block_service.py` and `click_redraw.py` (cascades, the redraw after a Sync). `src/clicknick/data/AGENTS.md` for `nickname_staging.py`, `comment_upgrade_service.py`, `system_nickname_service.py`, `row_service.py` and `import_service.py` (they open or receive an edit session). `src/clicknick/views/AGENTS.md` for `rung_diff.py`, `click_snapshot.py` and `nickname_staging.py` (Review Changes). `src/clicknick/SIMULATION.md` for `dap_service.py`, `sim_state.py`, `program_carry.py`, `link_annotation.py`, `console_completer.py`, `sim_hardware.py` and `physical_response.py` (the simulation). |
| `src/clicknick/views/` | `src/clicknick/views/AGENTS.md` (Review Changes). `src/clicknick/data/AGENTS.md` for `address_editor/` and `simulator_window.py` (they open edit sessions). `src/clicknick/data/AGENTS.md` for `redraw_splash.py` (the notice during the redraw after a Sync). `src/clicknick/SIMULATION.md` for `simulator_window.py`, `console_panel.py`, `sim_link_dialog.py`, `sim_palette.py` and `dataview_editor/` (the simulation). `src/clicknick/CONNECTION.md` for `dataview_editor/` (its DataView folder) and `overlay.py` (the autocomplete popup). |
| `src/clicknick/live/` | `src/clicknick/services/AGENTS.md` (`clicknick-cli` backup, restore and `rung apply`). `src/clicknick/views/AGENTS.md` for `rung apply`. `src/clicknick/data/AGENTS.md` for `dispatch.py` and `tag_commands.py` (they open edit sessions). |
| `src/clicknick/utils/` | `src/clicknick/CONNECTION.md` for `click_temp.py`. |
| `src/clicknick/ladder/` | `src/clicknick/ladder/AGENTS.md`. |
| `src/clicknick/widgets/` | `src/clicknick/SIMULATION.md` for `console_input.py` (the Console). `src/clicknick/CONNECTION.md` for `nickname_combobox.py` (the autocomplete popup). Only this file for the others. |
| `src/clicknick/detection/` | `src/clicknick/CONNECTION.md` for `window_detector.py` (the list of CLICK windows). Only this file for the others. |
| `src/clicknick/resources/` | Only this file. |
| `tests/` | `tests/AGENTS.md`, and the file for the code that the test covers. |
