# Development

## Setting Up uv

This project is set up to use [uv](https://docs.astral.sh/uv/) to manage Python and
dependencies. First, be sure you
[have uv installed](https://docs.astral.sh/uv/getting-started/installation/).

Then [fork the ssweber/clicknick
repo](https://github.com/ssweber/clicknick/fork) (having your own
fork will make it easier to contribute) and
[clone it](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository).

## Working with local pyrung

Keep the checkouts side by side (`clicknick`, `pyrung`, `pyclickplc`, and `laddercodec`). Run these commands
from the **clicknick directory**, using Windows **cmd**:

```bat
make install
make install-dev
set UV_NO_SYNC=1
make lint test
uv run --no-sync python -u -m clicknick
```

`make install-dev` installs `../pyclickplc`, `../pyrung`, and `../laddercodec` as editable
dependencies in ClickNick's `.venv`, so source edits in those checkouts are used directly. Restart
ClickNick after changing Python code. The Python module launch keeps stdout
and stderr visible in the terminal. Use the checkout launch command above;
a separately installed `uv tool` launcher has its own environment.

`--no-sync` keeps uv from replacing the local library installs with the released
packages from `uv.lock`. It does not install the local package by itself.
`UV_NO_SYNC=1` also protects the `uv run` commands inside `make lint` and
`make test`. In **PowerShell**, set it with:

```powershell
$env:UV_NO_SYNC = '1'
```

Both forms apply only to the current terminal session. cmd uses `set`, not
`export`. While testing local pyrung, use `make lint test`; bare `make`,
`make install`, and `make upgrade` include explicit dependency synchronization
and can restore the released package even with `UV_NO_SYNC` set.

### An import from pyrung fails

If ClickNick stops with an `ImportError` for a name from `pyrung`, the
environment probably holds released pyrung, and this ClickNick revision needs
the sibling checkout. Reinstall the local dependency, then restart ClickNick:

```bat
make install-dev
uv run --no-sync python -u -m clicknick
```

### Returning to released dependencies

In cmd:

```bat
set UV_NO_SYNC=
make install
```

In PowerShell, clear the variable with
`Remove-Item Env:UV_NO_SYNC -ErrorAction SilentlyContinue`, then run `make install`.
Use a ClickNick revision compatible with the released pyrung version.

## Releasing

The version comes from the git tag, so there is no version number to edit.

1. Publish the libraries ClickNick needs: `laddercodec` and `pyclickplc`, then `pyrung`.
2. On a branch off `main`, update their pins in `pyproject.toml` and `uv.lock` together. The
   whole runtime tree is pinned with `==`. If a new transitive dependency appears, add a pin for
   it and an entry in `PURPOSES` in `devtools/trust_report.py`.
3. Return to the released dependencies (above) and run `make lint test`. Try what changed by
   hand, because the tests can't drive CLICK.
4. Run `make docs-check`.
5. In `CHANGELOG.md`, condense `Unreleased` as its style comment says and move it under
   `## vX.Y.Z - YYYY-MM-DD`.
6. Run `make trust-report`. If a check is red here, the release fails later.
7. Open a pull request into `main`. When CI passes, squash-merge it.
8. Publish a GitHub release tagged `vX.Y.Z`. `.github/workflows/publish.yml` then builds on
   Windows, publishes to PyPI, and attaches the trust report and SBOM to the release. It also
   deploys the docs from the release's tag, except for a pre-release. The public site changes
   only at this step, because merges to `main` don't deploy it. To publish a docs fix between
   releases, or after you promote a pre-release, run Docs by hand:
   `gh workflow run docs.yml --ref main -f ref=<tag or commit>`. If `ref` is empty, Docs
   rebuilds the latest release.

## Basic Developer Workflows

The `Makefile` simply offers shortcuts to `uv` commands for developer convenience.
(For clarity, GitHub Actions don't use the Makefile and just call `uv` directly.)

### To Install Make:
1. Open PowerShell and run:
```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
irm get.scoop.sh | iex
```
2. Then install Make with Scoop:
```powershell
scoop install make
```

### Running Make:

```shell
# First, install all dependencies and set up your virtual environment.
# This simply runs `uv sync --all-extras --dev` to install all packages,
# including dev dependencies and optional dependencies.
make install

# Run uv sync, lint, and test:
make

# Build wheel:
make build

# Linting:
make lint

# Run tests:
make test

# Cross-backend oracle tests (Access ODBC vs the built-in Jet worker on one MDB).
# Needs an Access ODBC driver installed; not part of `make test` or CI:
make test-backend

# Build the wheel plus the release trust report and SBOM into dist/trust/
# (needs network for uv audit; TRUST_ARGS=--skip-audit when offline):
make trust-report

# Delete all the build artifacts:
make clean

# Upgrade dependencies to compatible versions:
make upgrade

# To run tests by hand:
uv run pytest   # all tests
uv run pytest -s src/module/some_file.py  # one test, showing outputs

# Build and install current dev executables, to let you use your dev copies
# as local tools:
uv tool install --editable .

# Dependency management directly with uv:
# Add a new dependency:
uv add package_name
# Add a development dependency:
uv add --dev package_name
# Update to latest compatible versions (including dependencies on git repos):
uv sync --upgrade
# Update a specific package:
uv lock --upgrade-package package_name
# Update dependencies on a package:
uv add package_name@latest

# Run a shell within the Python environment:
uv venv
source .venv/bin/activate
```

See [uv docs](https://docs.astral.sh/uv/) for details.

## IDE setup

If you use VSCode or a fork like Cursor or Windsurf, you can install the following
extensions:

- [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python)

- [Based Pyright](https://marketplace.visualstudio.com/items?itemName=detachhead.basedpyright)
  for type checking. Note that this extension works with non-Microsoft VSCode forks like
  Cursor.

## Documentation

- [uv docs](https://docs.astral.sh/uv/)

- [basedpyright docs](https://docs.basedpyright.com/latest/)

* * *

*This file was built with
[simple-modern-uv](https://github.com/jlevy/simple-modern-uv).*

## Jet database fallback

See [Jet sidecar research](research/jet-sidecar/README.md) for validation results,
standalone probes, and remaining platform checks. Production regression tests
run with `make test`.

## CLICK runner

`devtools/click_runner.py` drives CLICK v4 on this desktop with nobody at it. laddercodec and
pyrung use it to ask CLICK what it makes of a rung. The runner starts its own CLICK. In every
command but `new`, it connects to the one PLC on the LAN without reading its project. `paste`
pastes the CSV, runs Syntax Check, and saves. Then it decodes what CLICK saved:

```bat
set UV_NO_SYNC=1
uv run python devtools/click_runner.py paste rung.csv --out runs\one
uv run python devtools/click_runner.py record --out runs\dialogs
uv run python devtools/click_runner.py try cases.json --out runs\cases --wire --keep
uv run python devtools/click_runner.py export-nicknames --out runs\export --import nicknames.csv
uv run python devtools/click_runner.py new --cpu C2-03CPU --out runs\plus
uv run python devtools/click_runner.py new --cpu none --out runs\nocpu
```

`paste --add-end` adds an unconditional `end()` rung after the CSV's rungs before it pastes them,
unless the last rung is one already. `added_end` in `result.json` says whether it added one.
Leave the flag off when the CSV tests END itself, so that CLICK gets the CSV exactly as written.

`try` asks CLICK's instruction dialogs about each case in a JSON file. `devtools/editor_cases.json`
holds the cases for the rule table. Each case names the fields, mode and lists to set, and the
option buttons. You name a button by the label CLICK shows on it or by its id.

- With `--wire`, each case gets a rung of its own. An output instruction gets a contact `X001`
  before it, and a Compare gets a coil `Y001` after it.
- With `--keep`, each accepted case is saved under `saves\` in the `--out` folder.
- With both, the rung is also copied there, in the form that CLICK's Edit > Copy puts on the
  clipboard.

`export-nicknames` runs CLICK's File > Export > Nickname. CLICK writes the export into
`click\nicknames.csv` in the `--out` folder, and the runner copies its bytes to `export.csv` there.
`result.json` says what the bytes are: the byte order mark, whether they decode as UTF-8 and as
CP1252, the line ends, and each character that is not ASCII. With `--import`, the runner first
imports that nickname CSV, as the `import` command does.

`new` makes a project for one CPU through CLICK's own new-project wizard, and it never connects.
Give `--cpu` a model name from pyclickplc's catalog that the wizard lists, such as `C0-02DD1-D` or
`C2-03CPU`. The runner refuses any other name before CLICK starts. It picks the CPU. If User
Account Setup shows, the runner presses its Cancel. The project's admin account then has no
password. The runner saves the project as `<model>.ckp` in the `--out` folder. `result.json` holds
the CPU and the modules that the saved Project.ini names. It also holds that file's `[Sec21]`
section. A script that needs CLICK open on that project passes `on_new_project` to `Run` (see the
file's docstring). The runner then terminates CLICK, so CLICK's temp folder stays.

`new --cpu none` makes a project with no CPU. The runner presses Cancel where the wizard asks for
the CPU. CLICK then shows Startup again, and the runner closes it. The runner saves the project as
`none.ckp` and stops if its Project.ini names a CPU. `cpu` in `result.json` is null.

`result.json` in the `--out` folder (also printed on stdout) says how the run went, and `run.log`
logs each step. If a paste's rungs are not in the saved main program, the run ends `aborted`.
`record` dumps every window of CLICK at each step, so you can see a dialog that the runner does
not know yet.

The runner follows these rules:

- It refuses to start while CLICK is running or the screen is locked.
- It never writes to the PLC. An allowlist of commands in `devtools/click_desktop.py` enforces this.
- It never deletes CLICK's temp folder.
- It stops at any window it does not expect.
- After a crash, CLICK may say at Connect that it could not read the CPU type. The runner then
  presses OK in that box, waits 20 s and presses Connect again. It presses Connect at most
  three times.
- If CLICK exits after the runner presses a case's OK in `try`, a run with `--resume` records
  the case as `crashed` and does not try it again.
- If a CLICK error box appears, it stops and puts the box's code in `click_error`. The code is
  "PTC-013" when the PLC did not answer. The caller can then decide whether to run it again.

The file's docstring has the options, the rules and the result's fields. `tests/test_click_runner.py`
runs the runner against a fake CLICK. No test starts CLICK.

## Smoke test against CLICK

Run `make smoke` before a release. It checks ClickNick against new projects that the runner's
CLICK makes:

```bat
set UV_NO_SYNC=1
make smoke
make smoke SMOKE_ARGS="--cpu C2-03CPU --out runs\smoke"
```

`devtools/click_smoke.py` runs the runner's `new` mode once for each CPU: C0-00DD1-D, C0-02DD1-D,
C0-11DD1E-D, C0-12DD1E-2-D and C2-03CPU. Then it runs `new` for a project with no CPU (`--cpu
none`), and for a C0-11DD1E-D project with rungs (`--cpu rungs`). `--cpu` picks other CPUs,
`none` or `rungs`. While CLICK has the new project open, ClickNick connects to it with no window
and runs these checks:

- `paste`: only in `rungs`, before the other checks. ClickNick copies the nine rungs of
  `devtools/click_smoke_rungs.csv` as Review Changes' Copy does, and Copy adds their addresses
  to SC_.mdb. CLICK pastes the rungs at rung 1 and saves the project. The program in CLICK's
  save must be the program in the file. The rungs come from pyrung's tests. They use X001-X004,
  X006, X007, Y001 and Y002, two timers, two counters and a compare. If the paste fails, no
  other check runs on `rungs`.
- `load`: ClickNick reads the project's SC_.mdb.
- `build`: the workspace builds with no warning. In `rungs`, its `csv\main.csv` must hold the
  program that CLICK saved.
- `layout`: the Simulator's cards are the ones that `read_panel_layout` reads in the project's
  Project.ini. For a project with no CPU, the layout must have no CPU card. The Simulator then
  shows its No CPU card. For the projects in `devtools/click_smoke_layouts.json`, the cards must
  also be the cards recorded there. In `rungs`, the Simulator must count each X and Y that the
  program uses as used. The CPU has all of them, so the Simulator must show no card for
  unassigned I/O.
- `simulation`: the simulation starts and scans in RUN. In `rungs`, the simulation must read the
  program's X and Y addresses over Modbus, and switching X001 on must turn Y001 on.
- `panel`: only in `rungs`, after `simulation`. The smoke opens ClickNick's Simulator window on
  the simulation, and presses its panel with the `Driver` of `devtools/sim_driver.py`. The
  window shows on your desktop while the check runs. The smoke switches the CPU to STOP and
  back to RUN, and Y001 must then be off. It turns X001 on, and Y001 must light. It turns X001
  off, and Y001 must stay lit, because the program latches it. It double-clicks Y001, and the
  panel must show Y001 forced off, with its padlock and `Forces (1)`. A click on the padlock
  must release the force. If this check fails, the checks after it still run.
- `check_program`: Check Program and `clicknick-cli check` both run and report the same. In
  `rungs`, both report an error and a warning, because two Out coils drive Y002. Both must
  report the error, `COIL_CONFLICTING_OUTPUT` on Y002. The check keeps the reports and does not
  judge the other findings.
- `sync`: ClickNick gives DS100 the nickname `Smoke_Init` and the comment `50→60`. Sync must
  refuse the comment, because cp1252 has no `→`, and SC_.mdb must stay as it was. Then ClickNick
  changes the comment to `50°C`, and Sync must write the row with the initial value 0. A fresh
  load of SC_.mdb and CLICK's own nickname export must both show that row. The smoke does not
  redraw CLICK's ladder after the Sync, because the redraw opens CLICK's Import dialog.
- `csv_round_trip`: ClickNick's Export to CSV must write a cp1252 file, with `°` as the byte
  B0. CLICK imports the file into the same project with Delete Existing. SC_.mdb must then hold
  a row for each address in the file and no other row, and CLICK's nickname export must show
  `Smoke_Init` with `50°C`. The comparison is the same in `rungs`. ClickNick's file has no row
  for the program's addresses, because none of them has a nickname, a comment or a changed
  setting. CLICK 4.00 was observed to remove their rows from SC_.mdb when it imports the file
  with Delete Existing.
- `rung_apply`: the smoke adds a rung to the workspace's `src\plc\main.py`: a contact on X001
  that drives an Out coil on C1. `rung apply` must propose that rung for CLICK's empty main
  program. ClickNick copies the proposal as Review Changes' Copy does, and Copy adds X001 and C1
  to SC_.mdb. CLICK pastes the rungs at rung 1 and saves the project. After ClickNick rebuilds
  the workspace from that save, CLICK's saved program must start with the rung, Review Changes
  must have nothing left to paste, and `rung apply` must answer `(no changes)`. It needs an
  empty main program, so it does not run in `rungs`.

`sync` and `csv_round_trip` write SC_.mdb, so they run after the checks that read the project
as CLICK made it. They add about 13 s to each project. `result.json` holds the bytes of the
comment in SC_.mdb and in CLICK's export. `rung_apply` saves the project in CLICK, so it runs
last. It adds about 6 s to each project. `paste` adds about 5 s to `rungs`, and `panel` about
8 s. Each project takes about 30 s, and the whole smoke takes about 3.5 minutes.

The smoke writes its results into `--out` (by default `tmp\smoke\<date and time>`). Each
project gets a folder of its own. It holds the runner's `--out` folder, `runner\`, and a
`result.json` with each check's status (pass or fail), text and time. `rung_apply\` holds the
project that CLICK saved with the rung, and its Scr*.tmp files. `summary.json` lists every
project, and the smoke prints the same summary. The exit code is 0 when every project passed, 1
when any project failed and 2 when the smoke refused to start or stopped early. A project fails
when a check fails, when the runner does not end `ok`, when a scheduled callback raises, or when
port 502 is still in use after ClickNick closes. If a thread that a check started still runs
after ClickNick closes, the project fails and the smoke stops.

The smoke never connects to a PLC. It keeps away from your own ClickNick:

- It points `LOCALAPPDATA` at a folder in `--out`. ClickNick saves its settings and the
  simulator settings there. CLICK and the simulation also run with that `LOCALAPPDATA`.
- Each build writes a temporary workspace into the runner's CLICK's temp folder. Your settings,
  workspaces and simulator settings stay as they are.
- The simulation needs port 502. If another program has the port, such as your own ClickNick
  Simulator, the smoke refuses to start and names the port. Turn your Simulator off first.
- The runner refuses to start while any CLICK runs, so close CLICK first.

`make smoke` is not part of `make test` or CI. `tests/test_click_smoke.py` tests the smoke with a
fake runner.
