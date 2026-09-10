# Security

<!-- The report generator includes the marked sections from this checkout. -->
<!-- Keep version-specific examples and report instructions outside these sections. -->
<!-- trust-report:start -->

ClickNick is a Windows desktop tool that reads and edits CLICK projects and adds nickname
autocomplete to CLICK Programming Software.

ClickNick was written with security in mind: keep dependencies limited, prefer pure Python
where practical, run without administrator rights, and make the software's behavior easy to
inspect.

This page describes its file access, network connections, code execution, and installation
for IT and security review. ClickNick is [open source](https://github.com/ssweber/clicknick)
(AGPL-3.0), written and maintained by one author.

Each release includes a [trust report and dependency inventory](reports.md), generated
from the release source, built package, and dependency lock file. These are release checks,
not a formal security audit. A static scan shows what the code contains; it cannot prove
what it never does.

## Software characteristics

ClickNick installs no Windows services, drivers, or scheduled tasks. It has no telemetry,
analytics, or automatic update agent. Updates are initiated by the user.

ClickNick's own package is readable Python source, with no obfuscated or encrypted modules,
packed executables, or compiled code. Its installation also includes a Python interpreter
and dependencies with native binaries, identified in the release report. Source code for
every dependency is publicly available.

The default uv installation stays under the user's profile. Project exports and durable
workspaces are written to the folders the user chooses.

## Runtime behavior

- **Project database access.** ClickNick reads and writes `SC_.mdb` in the temporary folder
  CLICK creates when it opens a project. It uses Windows ODBC, or a 32-bit PowerShell worker
  using the Windows Jet engine when a 64-bit Access driver is unavailable.
- **Autocomplete.** ClickNick reads and fills text fields in CLICK Programming Software
  through standard Windows APIs, then sends Enter, Tab, or Escape after a nickname is
  selected. It installs no keyboard hook and injects no code into `Click.exe`.
- **Editor command listener.** While ClickNick is running, `clicknick-cli` can connect to
  its local TCP port to read or stage address edits, check workspace code, and apply ladder
  proposals. This listener runs even when the offline console is closed. It binds to
  `localhost`, with the port chosen by Windows. Connections are unauthenticated,
  and ClickNick does not check the connecting process's user identity. Other local users
  and processes that can reach the port can connect. Address edits are staged and undoable;
  they reach the project when the user saves.
- **PLC connection.** The Dataview editor connects over Modbus TCP (port 502 by default)
  after the user asks to go live, to the address they enter. It reads values and writes
  values when the user clicks Write.
- **Generated Python.** On project connection, ClickNick translates the ladder into Python
  and runs the generated code in-process to build the model behind Check Program. This
  step does not run files found in the project folder.
- **Workspace Python.** Check Program, applying a proposal, and the offline console run
  the user's editable workspace (`src/plc`, `run.py`, `project_to_csv.py`) in a child Python
  process. The `tag apply` command executes workspace `tags.py` inside ClickNick to export
  its nickname changes. These are intentional code execution features, with the signed-in
  user's permissions. Treat a workspace received from outside like any other script folder.
- **Documentation links.** Clicking a documentation link opens `github.com` or `pyrung.com`
  in the default browser.

ClickNick has no background internet connection for telemetry or updates. Installation
downloads are described below; workspace scripts can perform whatever file or network
operations their code requests.

## What endpoint monitoring will see

The paths below describe the default uv installation.

| Event | Cause |
|---|---|
| Unsigned `clicknick.exe` in `%USERPROFILE%\.local\bin` starts Python from `%APPDATA%\uv\tools\clicknick\` | Normal launch. uv generates the small entry-point launcher; ClickNick runs as `python.exe` or `pythonw.exe`. |
| Python starts `SysWOW64\...\powershell.exe -EncodedCommand ...` | The Jet database worker, on machines without a 64-bit Access driver. The full command and script identity are below. |
| Python listening on `127.0.0.1:<random port>` | The editor command listener for `clicknick-cli`; the offline console uses a separate `pyrung live` connection for simulation. |
| Python starts a child Python process | Check Program, applying a proposal, or the offline console running the user's workspace. |
| Python connects to `<PLC address>:502` | Dataview editor, after the user asks to go live. |
| Native `.pyd`, `.dll`, and `.exe` files appear under `%APPDATA%\uv\` | The Python interpreter and dependencies such as pywin32 and pyodbc. pywin32 includes `Pythonwin.exe` and `pythonservice.exe`; ClickNick does not run them. |
| `HKCU\Environment` PATH changed | The uv installer adds its executable directory to the user's PATH. |

The database worker's command line is:

```text
%SystemRoot%\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand <base64>
```

The payload is the text of the shipped `clicknick/resources/jet_sidecar.ps1` script,
with line endings normalized to LF, encoded as UTF-16LE and then Base64. Each release
report includes the shipped file's SHA256 for review. Project paths and values travel
separately as JSON on standard input; they are not inserted into PowerShell source.

The encoded invocation keeps the worker usable under Windows PowerShell's Restricted
execution policy, which permits commands but blocks script files invoked with `-File`.
It does not change execution policy or relax application-control rules. Endpoint tools
may flag the invocation; any exception depends on the controls in use. To use Access ODBC
without falling back to PowerShell, start `clicknick --db-backend odbc`. The
`--db-backend none` option uses CSV mode without either database backend.

## Installation and updates

[uv](https://docs.astral.sh/uv/) is an open-source Python package manager from
[Astral](https://astral.sh/). For ClickNick, it downloads the package and dependencies from
PyPI, installs them in an isolated environment, and creates the launcher. It also downloads
a Python interpreter if needed. ClickNick does not call uv at runtime.

Installation and upgrades use these hosts:

| Purpose | Hosts |
|---|---|
| uv installer | `astral.sh` |
| Python builds from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | `github.com`, `objects.githubusercontent.com` |
| ClickNick and Python dependencies | `pypi.org`, `files.pythonhosted.org` |

uv checks package files against hashes published by PyPI and Python downloads against
hashes built into uv. Installing ClickNick's wheel unpacks files; the wheel has no
install-time scripts.

If a script piped into PowerShell is against policy, install uv with
`winget install --id astral-sh.uv`. If your policy prefers pip, install ClickNick into a
virtual environment using Python 3.11 or newer. See [Install](../install.md).

To update: `uv tool upgrade clicknick`.

ClickNick pins its whole dependency tree to exact versions, so installing a given ClickNick
version installs exactly the dependency versions in that release's report. Dependency
updates, including security fixes, arrive only through a new ClickNick release, and every
release runs `uv audit` before it ships.

<!-- trust-report:end -->

## The trust report

Each release includes `clicknick-trust-report-<version>.html`, a self-contained page with
no scripts or external resources, and `clicknick-sbom-<version>.cyclonedx.json`, the
dependency inventory in [CycloneDX 1.5](https://cyclonedx.org/) format. Both are attached to
the GitHub release and mirrored under [Release reports](reports.md).

The report includes the security narrative from this page in the tagged source, followed
by four generated sections. Updating this page updates future reports automatically;
published reports retain the wording from their release. The narrative describes intended
behavior, while the checks provide the specific evidence listed below:

1. **Release summary.** Version, Python requirement, distribution counts, known
   vulnerabilities from `uv audit`, non-PyPI dependency count, unresolved license count,
   and SHA256 hashes of the SBOM, wheel, and PowerShell worker script.
2. **Release checks.** Mechanical checks over the lock file, built wheel, and ClickNick
   source: no HTTP client or telemetry dependency, no HTTP, FTP, or mail client imports,
   no download commands in shipped scripts, no Python decoded at runtime, no compiled code
   in the wheel, listeners bound to localhost, subprocesses limited to the same Python
   interpreter and built-in Windows PowerShell, and every dependency pinned to its locked
   version. A failed check fails the release.
3. **Runtime dependencies.** Package, version, pin, source, license, which package uses
   it, native code, and purpose for the release's runtime dependency set.
4. **Source transparency.** The source locations behind the checks, including URLs in
   runtime string literals, subprocess launch sites, and `exec` calls.

## Verify it yourself

To install a specific ClickNick release: `uv tool install clicknick==0.23.1`.

The report can be regenerated from the tagged source:

```powershell
git clone https://github.com/ssweber/clicknick
cd clicknick
git checkout v0.23.1                                   # the release under review
uv export --frozen --no-dev --format cyclonedx1.5      # the dependency list
uv audit --frozen --no-dev --no-group docs             # the vulnerability check
uv build
certutil -hashfile dist\clicknick-0.23.1-py3-none-any.whl SHA256
uv run python devtools/trust_report.py                 # regenerate the report into dist\trust
```

Compare the wheel hash with the
[PyPI release page](https://pypi.org/project/clicknick/#files) and with the report.
`uv tool dir` shows where the installed package's files live.

`uv build` reads the pinned build dependencies from `pyproject.toml`. Hatch uses stable
archive timestamps by default; leave `SOURCE_DATE_EPOCH` unset to use that default.
Git attributes select LF line endings for fresh checkouts. Compare the rebuilt wheel's
SHA256 with the release report to verify that its bytes match.

Use a clean checkout and the build recipe from the release tag being reviewed. Older tags
retain their original build settings, including Windows line-ending conversion. Normalizing
a new checkout does not change the bytes or hashes of those published packages.

<!-- trust-report:start -->

## Where things live on disk

Default locations for an installation through uv:

| Item | Location |
|---|---|
| uv itself | `%USERPROFILE%\.local\bin\uv.exe` |
| Python interpreter downloaded by uv | `%APPDATA%\uv\python\` |
| ClickNick and its dependencies | `%APPDATA%\uv\tools\clicknick\` |
| Launcher stub | `%USERPROFILE%\.local\bin\clicknick.exe` |
| uv download cache | `%LOCALAPPDATA%\uv\cache\` |
| Live-session files | The CLICK temp folder for the open project, or `%LOCALAPPDATA%\ClickNick\live\`. CLICK does not read these files. |
| Generated engineering workspace | `%TEMP%\clicknick_*` while running, or the folder the user chooses for a durable workspace |
| Project data it edits | `SC_.mdb` in `%LOCALAPPDATA%\Temp\CLICK (...)\`. CLICK writes it back into the `.ckp` on save. |

## Uninstall

```powershell
uv tool uninstall clicknick
```

This removes ClickNick's tool environment and launchers. User-saved workspaces and exports
remain in their chosen folders.

uv, its downloaded Python interpreters, and its cache remain available for other tools.
Removing `%APPDATA%\uv\` also removes other uv tool environments and shared Python builds.
Remove those shared directories only if you are retiring uv and all tools that use them;
the same applies to removing `%USERPROFILE%\.local\bin` from PATH, since other commands may
live there.

## Reporting a problem

Report security issues through the repository's
[private vulnerability reporting form](https://github.com/ssweber/clicknick/security/advisories/new).
For other problems, [open an issue](https://github.com/ssweber/clicknick/issues).
Include the release version and its trust report.

<!-- trust-report:end -->
