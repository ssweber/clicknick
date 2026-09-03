# Install ClickNick

ClickNick supports Windows 10 and 11 and CLICK Programming Software v2.60-v3.90.

## Install with `uv`

Open PowerShell and install `uv` if you do not already have it:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then install and run ClickNick:

```powershell
uv tool install clicknick
clicknick
```

To try the current release without installing it, run:

```powershell
uvx clicknick@latest
```

To upgrade an installed copy later:

```powershell
uv tool upgrade clicknick
```

## Install the Access driver

Check Program, Console, workspaces, and live nickname sync need the **64-bit Microsoft Access ODBC driver**. It lets ClickNick read the temporary database that CLICK creates for an open project.

See the [Access driver installation notes](https://github.com/ssweber/clicknick/issues/17) if ClickNick reports that the driver is missing.

Without the driver, ClickNick runs in CSV mode: load nicknames from a CSV export and use autocomplete, plus lighter versions of the Address Editor and Data View builder. Check Program, Console, and workspaces are unavailable.

## Start ClickNick

1. Open a `.ckp` project in CLICK Programming Software.
2. Save it. ClickNick reads what CLICK last saved.
3. Run `clicknick`.
4. Confirm that ClickNick shows the open project as connected.

Continue with [Getting started](getting-started.md).

## Pip alternative

Python 3.11 or newer is required:

```powershell
pip install clicknick
python -m clicknick
```

The `uv` installation is the recommended path because it manages ClickNick's Python environment separately from your other Python tools.
