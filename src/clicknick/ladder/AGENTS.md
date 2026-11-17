# Ladder Module Agent Workflow

## Scope

The encoder/decoder core lives in the standalone [`laddercodec`](https://github.com/ssweber/laddercodec) package. This directory (`ladder/`) contains **clipboard I/O, program service functions, and the CLI**:

- **program.py** — Service functions (encode, decode, MDB provisioning, program save/load). Pure logic, no print/input/sys.exit. Used by both CLI and GUI.
- **cli.py** — `clicknick-rung` CLI. Thin wrapper: argparse, interactive prompts, presentation. Calls program.py services.
- **clipboard.py** — Win32 clipboard interaction (copy/read/clear, Click format 522)

For encoder/codec work, **work in the laddercodec repo** (`../laddercodec`).

## Dependency

`laddercodec` is pinned exactly in `pyproject.toml` and `uv.lock` for releases. Updating the sibling checkout does not update ClickNick's installed codec. After publishing a new laddercodec release, update the pin and lockfile together, sync the environment, and run the ClickNick checks before releasing.

For temporary local codec development, you can use an editable install with `UV_NO_SYNC=1`. Keep the release metadata pinned to the published package.

## CLI usage

```bash
clicknick-rung guided FOLDER                # Interactive batch verify CSVs
clicknick-rung guided FOLDER --list         # List CSVs with descriptions
clicknick-rung guided FOLDER --restart      # Clear progress, start fresh
clicknick-rung program load FOLDER          # Load CSV bundle into Click (guided paste)
clicknick-rung program save FOLDER          # Decode Scr*.tmp → main.csv + subroutines/
clicknick-rung load FILE                    # Encode .csv/.bin → clipboard
clicknick-rung save FILE                    # Clipboard → .bin/.csv/both
clicknick-rung --mdb-path SC_.mdb ...       # Explicit MDB path (any subcommand)
```

### Interactive prompt (guided)

For each CSV: shows description, CSV shape, copies to clipboard, then prompts:

- **[w]orked** — paste worked; copy rung back for comparison/saving
- **[c]rashed** — Click crashed; optionally record details in progress log
- **[n]ot as expected** — pasted but looks wrong; record description in progress log, optionally save `.bin`
- **[s]kip** — skip this fixture
- **[q]uit** — stop

Progress is tracked in `verify_progress.log` in the folder. Re-running resumes automatically; `--restart` clears it.

### MDB integration

The CLI detects the running Click project's SC_.mdb by itself. Before it pastes, it makes sure the operand addresses exist. Contacts and coils require this.

If `--mdb-path` names no file, `load`, `guided` and `program load` stop with an error before they copy anything. `save` and `program save` do not read the option. If adding the addresses to that SC_.mdb fails, `load` stops with an error and copies nothing. `guided` and `program load` print the error on stderr and offer to try again. If you skip or quit there, the CSV is recorded as an error, and the run exits 1. Without `--mdb-path`, the CLI prints a warning on stderr when the CLICK window has no SC_.mdb or adding the addresses fails, and copies the rungs anyway.

## Shell hygiene

Never inline multi-line content in bash commands (echo, printf, python -c, cat <<EOF).
Use the Write/Edit tool to create .py scripts, then run them with `uv run`.
