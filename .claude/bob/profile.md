# BOB profile: ClickNick

Repo-specific rules for the bob plugin's skill. The plugin's rules for every repo come first;
this file adds ClickNick's.

The plugin is installed once per clone: `claude plugin install bob@bob --scope project` (and once
per machine, `claude plugin marketplace add ssweber/bob`). Until it is, no hook guards the repo:
check `/plugins` before dispatching builders.

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
  Sam can check in CLICK. Add to it. Don't repeat the list in chat.
- The main checkout may hold Sam's uncommitted `pyproject.toml`/`uv.lock` and untracked
  `*.bin`/`*.csv` in the repo root: leave them alone.

## Environment (put in every builder and reviewer brief)

- Each worktree has its own `.venv`, made from its `uv.lock` with the released pyclickplc, pyrung and
  laddercodec. The orchestrator makes it after `worktree new`:
  `env -u UV_PROJECT_ENVIRONMENT uv sync --locked --all-extras --dev --project <worktree>`. A builder or
  reviewer never uses the main checkout's `.venv`, and never runs `uv run`, `uv sync` or `make` in the main
  checkout. The main checkout's `.venv` holds Sam's `make install-dev` (the local sibling checkouts), and a sync
  there puts the released packages back. Agents from other repos that work in this one follow the same rule.
- A branch that needs an unreleased sibling installs it into its own `.venv`:
  `uv pip install --python <worktree>/.venv/Scripts/python.exe <sibling checkout or worktree>`. It merges only
  after that sibling's release. Its pull request says so and stays open until then. With a sibling installed,
  every `uv run` also takes `UV_NO_SYNC=1`.
- Run `make lint UV_NO_SYNC=1` and `timeout 900 make test UV_NO_SYNC=1`, never a bare `make`, which runs
  `make install`. The hook wraps `make` in a 600 s timeout unless a leading `timeout N` says otherwise, and the
  suite can pass 600 s under load. With no queue, nothing but this rule refuses a bare `make`.
- Use `make` commands for the suite, not a bare `uv run pytest`. Targeted pytest is fine. Do not
  put `cd` before commands in the main checkout. Do not inline multi-line content in shell
  commands (heredocs, `python -c`). Write a file with Write, then run it.
- Write files with LF line endings. `.gitattributes` says `eol=lf`, but some working-tree files
  are CRLF, so normalise them before you match text in them.

## Local gate

`make lint UV_NO_SYNC=1` and `timeout 900 make test UV_NO_SYNC=1` in the worktree, both green on
the last commit with a clean worktree. The full suite is about 2 minutes, serial. Where a branch
touches the docs, also `timeout 900 make docs-check`, last. Its `uv run` syncs the worktree's `.venv` to the
lock with the docs group, which replaces any sibling installed there.

## Correctness contract (put in every builder and reviewer brief)

- The root AGENTS.md and the files its table points to are the contract. They require:
  - the three-layer store (base, overrides, visible) with one `_derive`;
  - only `AddressStore` writes its layers;
  - every edit goes through `edit_session()` and commits all or nothing;
  - views are passive observers that refresh the changed keys;
  - `services/` and `data/` never import tkinter (`tests/test_store_boundaries.py`);
  - one home per fact (`ClickNickApp._data`, `_click`);
  - no compatibility shims.
- Ground truth is what CLICK Programming Software (v2.60-v4.00) writes, reads and shows: its
  SC_.mdb, Scr*.tmp saves, .cdv files, the clipboard. Never edit a recorded expectation to fit
  the code.
- Agents never touch Sam's real CLICK. Do not send keystrokes or clicks into a CLICK window. Do
  not read or write a live project's temp folder or SC_.mdb. Do not launch ClickNick against it.
  Tests and probes use fixtures, temp copies and fakes. Questions only CLICK can answer go to
  the roadmap's "Open user checks".
- A bug fix comes with a regression test that fails on the base and passes on the branch, at the
  lowest layer that shows it (service or store over a Tk view).
- CHANGELOG (Unreleased) moves with what a user sees, in every pull request. Docs (`docs/`,
  `docs/help/`) move only where what a user does changes.
- Prose follows the Writing section of AGENTS.md.

## Models

- Builders: use Opus at `effort: high` for the store (`address_store.py`, `edit_session.py`,
  `_derive`, undo), database backends and writes (`utils/mdb*`, Jet worker), Review Changes and
  rung diff, and simulation session/DAP. Use Sonnet for one view's behaviour, and for tests-only
  or docs-only work.
- Reviewers: use Opus for the store, database writes, Review Changes and concurrency. Use Sonnet
  for a single view, tests, docs, CI and workflow changes.
- Read-only code questions go to `bob:bob-investigator`, on Sonnet. Send a bug sweep of a
  component to `bob:bob-reviewer` with the component instead of a branch. The sweep may run
  targeted tests and bounded probes.

## Machine budget

- Run up to ~5 builders in parallel. Sweep reviewers are read-only and may run more. Only
  `targeted_slots` (3) bounded runs go at once.
- GitHub Actions jobs are shared with the other repos (pyrung, laddercodec, pyclickplc). A
  check that sits queued is usually waiting for a runner. It is not failing.
- Read a command's exit code directly, never through a pipe without `pipefail`.

## Ground truth

Sam runs CLICK and can check a database write, a pasted rung or a Dataview in it. Collect
those checks in the roadmap's "Open user checks". A pull request that needs one stays open.

## Gotcha

Agent `isolation: worktree` may fail here, because the cwd says `documents` and git says
`Documents`. Always use `R worktree new`, and give the builder the path in its brief.
