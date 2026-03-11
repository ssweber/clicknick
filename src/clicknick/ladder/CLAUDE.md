# Ladder Verify — CLAUDE Workflow

## Scope

The encoder/decoder core lives in the standalone [`laddercodec`](https://github.com/ssweber/laddercodec) package. This directory (`ladder/`) contains only **clipboard I/O and golden fixture verification** against live CLICK software:

- **capture_verify.py** — CLI for verifying golden fixtures (encode → clipboard → paste → compare)
- **clipboard.py** — Win32 clipboard interaction (copy/read/clear, Click format 522)
- **DEFINITIONS.md** has moved to the laddercodec repo.

For encoder/codec work, **work in the laddercodec repo** (`../laddercodec`).

## Dependency

`laddercodec` is an editable local dep. Both repos must be sibling directories:

```toml
[tool.uv.sources]
laddercodec = { path = "../laddercodec", editable = true }
```

## Verify workflow

Golden CSV/BIN pairs live in **laddercodec** at `tests/fixtures/ladder_captures/golden/`.

```bash
clicknick-ladder-verify                         # Batch verify all golden fixtures
clicknick-ladder-verify --list                  # List fixtures with bin sizes
clicknick-ladder-verify --copy nc-1row-empty    # Encode + copy to clipboard
clicknick-ladder-verify --read nc-1row-empty    # Read clipboard + compare
clicknick-ladder-verify --skip-to nc-3row-t     # Resume batch from fixture
clicknick-ladder-verify --folder path/to/csvs   # Verify arbitrary CSVs from folder
clicknick-ladder-verify --mdb-path SC_.mdb ...  # Explicit MDB path
```

### Interactive prompt

Both golden batch and `--folder` modes use the same interactive loop. For each fixture it shows the description, CSV shape, and copies to clipboard, then prompts:

- **[p]asted** — paste worked; copy rung back for comparison (golden) or saving (folder)
- **[c]rashed** — Click crashed; optionally record details as `.note.txt`
- **[n]ot as expected** — pasted but looks wrong; record description as `.note.txt`, optionally save `.bin`
- **[s]kip** — skip this fixture
- **[q]uit** — stop, mark remaining as skipped

Results summary is printed at the end. `--folder` mode also writes `results_YYYYMMDD_HHMMSS.txt` to the folder.

### MDB integration

Auto-detects the running Click project's SC_.mdb and ensures operand addresses exist before pasting (required for contacts/coils).

## Shell hygiene

Never inline multi-line content in bash commands (echo, printf, python -c, cat <<EOF).
Use the Write/Edit tool to create .py scripts, then run them with `uv run`.
