# BOB profile: ClickNick

Repo-specific rules for the bob plugin's skill. The plugin's rules for every repo come first;
this file adds ClickNick's.

## Paths and branches

- Main checkout `C:/Users/Sam/Documents/GitHub/clicknick`. No merge queue: every branch goes
  into `main` through a pull request, gated by CI (`ci` and the docs `build`), and is
  squash-merged.
- Worktrees `../clicknick-wt/<name>` on `bob/<name>`, from `origin/main`
  (`R worktree new <name>`). A branch outside an arc may take a plain name (`--branch`).
- Job notes (`<jobs>`): `../clicknick-wt/buildbot/jobs/<name>/{BRIEF,HANDOFF,REVIEW,PR,LEDGER}.md`.
  Arc docs live there too, outside the repo. One arc doc: fold rulings and leftovers into it,
  not side notes.
- The roadmap is `scratchpad/roadmap.md`. Its "Open user checks" section collects what only
  Sam can check in CLICK; add to it, don't repeat the list in chat.
- The main checkout may hold Sam's uncommitted `pyproject.toml`/`uv.lock` and untracked
  `*.bin`/`*.csv` in the repo root: leave them alone.

## Environment (put in every builder and reviewer brief)

- ClickNick is developed against the local `pyclickplc`, `pyrung` and `laddercodec` checkouts
  beside it (development.md). A new worktree needs, once:
  `make install install-dev SIBLINGS=C:/Users/Sam/Documents/GitHub`. After that every
  `make lint`, `make test` and `uv run` runs with `UV_NO_SYNC=1`, or uv re-syncs and drops the
  local checkouts.
- A branch that needs an unreleased sibling is tested locally and merges only after that
  sibling's release; its pull request says so and stays open until then.
- `make` commands, not bare `uv run pytest` for the suite; targeted pytest is fine. No `cd`
  before commands in the main checkout. No multi-line content inlined in shell commands
  (heredocs, `python -c`): write a file with Write, then run it.
- Write files with LF line endings (`.gitattributes` says `eol=lf`; some working-tree files
  are CRLF, so normalise before matching text in them).

## Local gate

`make lint UV_NO_SYNC=1` and `make test UV_NO_SYNC=1` in the worktree, both green on the last
commit with a clean worktree. The full suite is about 2 minutes, serial. Where a branch touches
the docs, also `make docs-check` (it re-syncs the environment, so run it last).

## Correctness contract (put in every builder and reviewer brief)

- AGENTS.md is the contract: the three-layer store (base, overrides, visible) with one
  `_derive`; only `AddressStore` writes its layers; every edit goes through `edit_session()`
  and commits all or nothing; views are passive observers that refresh the changed keys;
  `services/` and `data/` never import tkinter (`tests/test_store_boundaries.py`); one home per
  fact (`ClickNickApp._data`, `_click`); no compatibility shims.
- Ground truth is what CLICK Programming Software (v2.60-v4.00) writes, reads and shows: its
  SC_.mdb, Scr*.tmp saves, .cdv files, the clipboard. Never edit a recorded expectation to fit
  the code.
- Agents never touch Sam's real CLICK: no keystrokes or clicks into a CLICK window, no
  reading or writing a live project's temp folder or SC_.mdb, no launching ClickNick against it.
  Tests and probes use fixtures, temp copies and fakes. Questions only CLICK can answer go to
  the roadmap's "Open user checks".
- A bug fix comes with a regression test that fails on the base and passes on the branch, at the
  lowest layer that shows it (service or store over a Tk view).
- CHANGELOG (Unreleased) moves with what a user sees, in every pull request. Docs (`docs/`,
  `docs/help/`) move only where what a user does changes. Prose is plain and direct, in the
  tone of AGENTS.md and the CHANGELOG.

## Models

- Builders: Opus at `effort: high` for the store (`address_store.py`, `edit_session.py`,
  `_derive`, undo), database backends and writes (`utils/mdb*`, Jet worker), Review Changes and
  rung diff, simulation session/DAP; Sonnet for one view's behaviour, tests-only or docs-only.
- Reviewers: Opus for the store, database writes, Review Changes and concurrency; Sonnet for a
  single view, tests, docs, CI and workflow changes.
- Read-only code questions: `bob:bob-investigator`, Sonnet. A bug sweep of a component (it may
  run targeted tests and bounded probes) goes to `bob:bob-reviewer` with the component instead
  of a branch.

## Machine budget

- Up to ~5 builders in parallel; sweep reviewers are read-only and may run more. Only
  `targeted_slots` (3) bounded runs go at once.
- GitHub Actions jobs are shared with the other repos (pyrung, laddercodec, pyclickplc): a
  check that sits queued is usually waiting for a runner, not failing.
- Read a command's exit code directly, never through a pipe without `pipefail`.

## Ground truth

Sam runs CLICK and can check a database write, a pasted rung or a Dataview in it. Collect
those checks in the roadmap's "Open user checks"; a pull request that needs one stays open.

## Gotcha

Agent `isolation: worktree` may fail here (cwd `documents` vs git `Documents` case mismatch):
always use `R worktree new` and brief the builder with the path.
