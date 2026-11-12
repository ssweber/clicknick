# BOB profile: ClickNick

Repo-specific rules for the /bob skill. Another repo replaces this file.

## Paths

- Main checkout `C:/Users/Sam/Documents/GitHub/clicknick`, base branch `dev`. The user
  squash-merges dev into main and cuts releases; never touch main. Trains land on dev locally;
  do not push dev or any bob/* branch unless the user asks.
- Worktrees `../clicknick-wt/<name>` on `bob/<name>`; mergeq home `../clicknick-wt/buildbot`
  (queue, logs, results, `jobs/<id>/{BRIEF,HANDOFF,REVIEW,LEDGER}.md`).
- Arc docs live under the home, outside the repo (`jobs/<arc>/ARC.md`), so they never need a
  commit to dev while a train gates. One arc doc: fold rulings and leftovers into it, not side
  notes.
- The main checkout may hold the user's uncommitted `pyproject.toml`/`uv.lock` and untracked
  `*.bin`/`*.csv` in the repo root: leave them alone, stash only your own paths around `land`.

## Environment (put in every builder and reviewer brief)

- ClickNick is developed against the local `pyclickplc`, `pyrung` and `laddercodec` checkouts
  beside it (development.md). A new worktree needs, once:
  `make install install-dev SIBLINGS=C:/Users/Sam/Documents/GitHub`. After that every
  `make lint`, `make test` and `uv run` runs with `UV_NO_SYNC=1`, or uv re-syncs and drops the
  local checkouts. The gate does the same (mergeq.toml `install`, stages).
- `make` commands, not bare `uv run pytest` for the suite; targeted pytest is fine. No `cd`
  before commands in the main checkout. No multi-line content inlined in shell commands
  (heredocs, `python -c`): write a file with Write, then run it.
- The full suite is about 2 min, serial. Every stage is light.

## Correctness contract (put in every builder and reviewer brief)

- AGENTS.md is the contract: the three-layer store (base, overrides, visible) with one
  `_derive`; only `AddressStore` writes its layers; every edit goes through `edit_session()`
  and commits all or nothing; views are passive observers that refresh the changed keys;
  `services/` and `data/` never import tkinter (`tests/test_store_boundaries.py`); one home per
  fact (`ClickNickApp._data`, `_click`); no compatibility shims.
- Ground truth is what CLICK Programming Software (v2.60-v4.00) writes, reads and shows: its
  SC_.mdb, Scr*.tmp saves, .cdv files, the clipboard. Never edit a recorded expectation to fit
  the code.
- Agents never touch the user's real CLICK: no keystrokes or clicks into a CLICK window, no
  reading or writing a live project's temp folder or SC_.mdb, no launching ClickNick against it.
  Tests and probes use fixtures, temp copies and fakes. Questions only CLICK can answer go to
  the user, batched.
- A bug fix comes with a regression test that fails on the base and passes on the branch, at the
  lowest layer that shows it (service or store over a Tk view).
- CHANGELOG (Unreleased) moves with what a user sees. Docs (`docs/`, `docs/help/`) move only where
  what a user does changes. Prose is plain and direct, in the tone of AGENTS.md and the CHANGELOG.

## Train checks

None. Trains gate on `train` (lint, test, docs).

## Models

- Builders: Opus at `effort: high` for the store (`address_store.py`, `edit_session.py`,
  `_derive`, undo), database backends and writes (`utils/mdb*`, Jet worker), Preview Changes and
  rung diff, simulation session/DAP; Sonnet for one view's behaviour, tests-only or docs-only.
- Reviewers: Opus for the store, database writes, Preview Changes and concurrency; Sonnet for a
  single view, tests, docs.
- Read-only code questions: `bob-investigator`, Sonnet. A bug sweep of a component (it may run
  targeted tests and bounded probes) goes to `bob-reviewer` with the component instead of a
  branch.

## Machine budget

- Up to ~5 builders in parallel; sweep reviewers are read-only and may run more. Only
  `targeted_slots` (3) test runs go at once. One gate job at a time (the queue serializes it).
- Read a gate's exit code directly, never through a pipe without `pipefail`.

## Ground truth

The user runs CLICK and can check a database write, a pasted rung or a Dataview in it. Collect
those questions and list them in milestone reports, batched.

## Gotcha

Agent `isolation: worktree` may fail here (cwd `documents` vs git `Documents` case mismatch,
as in pyrung): always use `mergeq worktree new` and brief the builder with the path.
