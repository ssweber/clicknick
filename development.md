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

Keep the checkouts side by side (`clicknick` and `pyrung`). Run these commands
from the **clicknick directory**, using Windows **cmd**:

```bat
make install
make install-pyrung-dev
set UV_NO_SYNC=1
make lint test
uv run --no-sync clicknick
```

`make install-pyrung-dev` installs `../pyrung` as an editable dependency in
ClickNick's `.venv`, so source edits in that checkout are used directly. Restart
ClickNick after changing Python code. Use the checkout launch command above;
a separately installed `uv tool` launcher has its own environment.

`--no-sync` keeps uv from replacing the local pyrung install with the released
package from `uv.lock`. It does not install the local package by itself.
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
make install-pyrung-dev
uv run --no-sync clicknick
```

The new Check Program selection workflow requires the matching pyrung changes.
Before releasing ClickNick, publish that pyrung version and update ClickNick's
minimum dependency and lockfile together.

### Returning to released dependencies

In cmd:

```bat
set UV_NO_SYNC=
make install
```

In PowerShell, clear the variable with
`Remove-Item Env:UV_NO_SYNC -ErrorAction SilentlyContinue`, then run `make install`.
Use a ClickNick revision compatible with the released pyrung version.

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
