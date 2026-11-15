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

### Missing validation.config module

If you see `No module named pyrung.core.validation.config`, the environment
likely contains released pyrung instead of the paired development checkout.
Reinstall the local dependency, then restart ClickNick:

```bat
make install-dev
uv run --no-sync python -u -m clicknick
```

The new Check Program selection workflow requires the matching pyrung changes.
Channel parameter import also requires the matching local pyclickplc checkout.

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
   whole runtime tree is pinned with `==`, so a new transitive dependency also needs a pin and
   an entry in `PURPOSES` in `devtools/trust_report.py`.
3. Return to the released dependencies (above) and run `make lint test`. Try what changed by
   hand: the tests can't drive CLICK.
4. Run `make docs-check`.
5. In `CHANGELOG.md`, condense `Unreleased` as its style comment says and move it under
   `## vX.Y.Z - YYYY-MM-DD`.
6. Run `make trust-report`. A red check here fails the release later.
7. Open a pull request into `main`; once CI passes, squash-merge it.
8. Publish a GitHub release tagged `vX.Y.Z`. `.github/workflows/publish.yml` builds on Windows,
   publishes to PyPI, attaches the trust report and SBOM to the release, and deploys the docs
   from the release's tag (not for a pre-release). The public site changes only here: merges to
   `main` don't deploy it. To put a docs fix up between releases, or after promoting a
   pre-release, run Docs by hand: `gh workflow run docs.yml --ref main -f ref=<tag or commit>`
   (an empty `ref` rebuilds the latest release).

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

`devtools/click_runner.py` drives CLICK v4 on this desktop with nobody at it, so laddercodec and
pyrung can ask CLICK what it makes of a rung. It starts its own CLICK, connects to the one PLC on
the LAN without reading its project, pastes the CSV, runs Syntax Check, saves, and decodes what
CLICK saved:

```bat
set UV_NO_SYNC=1
uv run python devtools/click_runner.py paste rung.csv --out runs\one
uv run python devtools/click_runner.py record --out runs\dialogs
```

`result.json` in the `--out` folder (also on stdout) says how the run went, and `run.log` logs
each step. A paste whose rungs are not in the saved main program ends the run `aborted`. `record`
dumps every window of CLICK at each step, to see a dialog the runner does not know yet. It
refuses to start while CLICK runs or the screen is locked, never writes to the PLC (an allowlist
of commands, in `devtools/click_desktop.py`), never deletes CLICK's temp folder, and stops at any
window it does not expect. The file's docstring has the options, the rules and the result's
fields. `tests/test_click_runner.py` runs it against a fake CLICK; no test starts CLICK.
