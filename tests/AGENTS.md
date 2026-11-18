# Tests

The root `AGENTS.md` says how to run the tests.

The tests live in `tests/`, with `tests/ladder/`. pytest's `testpaths` lists `src` and `tests`, and
`python_files` is `*.py`. So pytest also imports every module under `src`, but `src` holds no tests.

## Core data tests

- `test_address_store.py` covers edit sessions, undo and redo, dirty state, no-op edits, base and overlay
  merging, Discard, observers, system nickname validation, external database updates, derived-state
  regressions, Sync refusing rows with errors, `loaded_with_error` across reloads, Sync against a live database
  and the sync listeners. The cascades are tested in `test_store_cascades.py`.
- `test_store_oracle.py` runs random sequences of edits, undo, redo, Discard, Sync and CLICK writes. The kept
  state must equal a full rebuild from the same inputs, and each edit must follow the cascade rules.
- `test_store_cascades.py` tests the block tag and Retentive cascades: the T/TD and CT/CTD pairs, and open and
  close tags renamed in place.
- `test_store_boundaries.py` checks three source rules. Only the store writes its layers. Nothing outside the
  store uses `_current_session`. `services/`, `data/` and `simulation_session.py` never import tkinter. A fourth
  test checks that the layer-write detector catches each form of write.
- `test_pyrung_surface.py` checks that ClickNick imports pyrung only from its public modules: `pyrung`,
  `pyrung.click`, `pyrung.validation`, `pyrung.live` and `pyrung.circuitpy`. It reads every import in `src`,
  `tests` and `devtools`. It also reads the `from pyrung... import` and `import pyrung...` lines in program
  text inside a string, and any other string that names an internal pyrung module, such as a
  `monkeypatch.setattr` target. Each name must be in its module's `__all__`. `USED_NAMES` lists every pyrung
  name that ClickNick uses. If a pyrung release drops one of them, this test fails. A test checks that
  `USED_NAMES` lists exactly the names that the code imports. When you import a pyrung name or stop using one,
  change `USED_NAMES` to match.
- `test_data_session.py` tests the window lifecycle and the save prompts when data is closed or replaced.
- `test_mutable_row_builder.py` tests the builder and its `changes()` output.
- `test_address_model.py` covers address keys, the address range of each memory type, nickname, comment and
  initial-value validation, the data type constants, the `AddressRow` class and the block tag helpers. The
  `AddressRow` tests cover the frozen dataclass, `replace` making a new row, the Initial Value and Retentive
  rules, and the derived properties.

## Service tests

The service tests need no Tk window. They still load tkinter, because importing `clicknick` runs
`src/clicknick/__init__.py`, which imports `app.py`. `test_blocktag.py` imports only pyclickplc.

- `test_block_service.py` covers block colors, the rename and delete of the matching tag, block name
  availability and duplicate block names, the `_D` tags of the T/TD and CT/CTD pairs, and renaming or removing
  a block tag.
- `test_row_service.py` tests fill down, clone structure and the edit session integration.
- `test_blocktag.py` tests pyclickplc's block tag functions: parsing edge cases, finding the paired tag, and
  block ranges.

## Backup tests

`test_backup_oracle.py` checks the backup rules in `src/clicknick/services/AGENTS.md`. It runs random edits,
builds, backups and restores, with injected copy, move, time-file and prune failures.
