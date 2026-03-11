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
clicknick-ladder-verify                         # Batch verify all fixtures
clicknick-ladder-verify --list                  # List available fixtures
clicknick-ladder-verify --copy nc-1row-empty    # Encode + copy to clipboard
clicknick-ladder-verify --read nc-1row-empty    # Read clipboard + compare
clicknick-ladder-verify --mdb-path SC_.mdb ...  # Explicit MDB path
```

The MDB integration auto-detects the running Click project's SC_.mdb and ensures operand addresses exist before pasting (required for contacts/coils).

## Shell hygiene

Never inline multi-line content in bash commands (echo, printf, python -c, cat <<EOF).
Use the Write/Edit tool to create .py scripts, then run them with `uv run`.
