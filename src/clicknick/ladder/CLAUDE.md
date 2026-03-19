# Ladder Rung CLI — CLAUDE Workflow

## Scope

The encoder/decoder core lives in the standalone [`laddercodec`](https://github.com/ssweber/laddercodec) package. This directory (`ladder/`) contains only **clipboard I/O and fixture verification** against live CLICK software:

- **capture_verify.py** — `clicknick-rung` CLI (load/save/guided verify)
- **clipboard.py** — Win32 clipboard interaction (copy/read/clear, Click format 522)

For encoder/codec work, **work in the laddercodec repo** (`../laddercodec`).

## Dependency

`laddercodec` is an editable local dep. Both repos must be sibling directories:

```toml
[tool.uv.sources]
laddercodec = { path = "../laddercodec", editable = true }
```

## CLI usage

```bash
clicknick-rung guided FOLDER                # Interactive batch verify CSVs
clicknick-rung guided FOLDER --list         # List CSVs with descriptions
clicknick-rung guided FOLDER --restart      # Clear progress, start fresh
clicknick-rung load FILE                    # Encode .csv/.bin → clipboard
clicknick-rung save FILE                    # Clipboard → .bin/.csv/both
clicknick-rung --mdb-path SC_.mdb ...       # Explicit MDB path (any subcommand)
```

### Interactive prompt (guided)

For each CSV: shows description, CSV shape, copies to clipboard, then prompts:

- **[w]orked** — paste worked; copy rung back for comparison/saving
- **[c]rashed** — Click crashed; optionally record details as `.note.txt`
- **[n]ot as expected** — pasted but looks wrong; record description as `.note.txt`, optionally save `.bin`
- **[s]kip** — skip this fixture
- **[q]uit** — stop

Progress is tracked in `verify_progress.log` in the folder. Re-running resumes automatically; `--restart` clears it.

### MDB integration

Auto-detects the running Click project's SC_.mdb and ensures operand addresses exist before pasting (required for contacts/coils).

## Shell hygiene

Never inline multi-line content in bash commands (echo, printf, python -c, cat <<EOF).
Use the Write/Edit tool to create .py scripts, then run them with `uv run`.
