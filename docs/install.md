# Install ClickNick

ClickNick supports Windows 10 and 11 and CLICK Programming Software v2.60-v4.00.

## Install with `uv`

Open PowerShell and install `uv` if you do not already have it:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

On a managed machine, `winget install --id astral-sh.uv` installs the same thing without
running a downloaded script.

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

Need to clear this with IT first? Send them [Security](security/index.md): what ClickNick
installs, what it talks to, and a per-release dependency report.

## Start ClickNick

1. Open a `.ckp` project in CLICK Programming Software.
2. Save it. ClickNick reads what CLICK last saved.
3. Run `clicknick`.
4. Confirm that ClickNick shows the open project as connected.

Continue with [Getting started](getting-started.md).

<span id="install-the-access-driver"></span>
<span id="test-a-specific-database-backend"></span>

## Database connection

ClickNick connects automatically. On Windows x64, a separate database driver normally isn't needed, and the first connection can take a few seconds. If connecting fails, open **Help > About ClickNick > Test Connection**. [Connection help](help/index.md#database-connection) covers the rest, including [connection options](help/index.md#connection-options) and CSV mode.

## Pip alternative

Python 3.11 or newer is required:

```powershell
pip install clicknick
python -m clicknick
```
