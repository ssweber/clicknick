# Ladder Capture Workflow — CLAUDE Workflow

## Shell hygiene
Never inline multi-line content in bash commands (echo, printf, python -c, cat <<EOF).
This triggers Claude Code's quoted-newline security check and stalls the workflow.
Instead:
- Use the Write/Edit tool to create .py scripts, then run them with `uv run`.
- For quick Python one-liners, keep them truly single-line.

## Scope

The encoder/decoder core has been **extracted to the standalone [`laddercodec`](https://github.com/ssweber/laddercodec) package**. This directory (`ladder/`) contains only the **capture/testing workflow** that exercises laddercodec against live CLICK software:

- **capture_cli.py** — CLI for ladder capture verify/prepare/complete workflows
- **capture_workflow.py** — Shared workflow engine (used by CLI and TUI frontends)
- **capture_registry.py** — Manifest registry for scratchpad capture tracking
- **clipboard.py** — Windows clipboard interaction utilities (copy/read/clear)
- **__init__.py** — Re-export shim from laddercodec for convenience imports

For encoder/codec work (encode.py, codec.py, model.py, topology.py, empty_multirow.py, csv/), **work in the laddercodec repo** (`../laddercodec`).

## Import patterns

Clicknick modules import directly from `laddercodec`, not from local files:

```python
# capture_workflow.py
from laddercodec import ClickCodec, HeaderSeed
from laddercodec.csv.shorthand import format_comment_shorthand_row, normalize_shorthand_row
from laddercodec.topology import HEADER_ENTRY_BASE, cell_offset, header_structural_equal, parse_wire_topology

# capture_registry.py
from laddercodec.csv.shorthand import normalize_shorthand_row, render_shorthand_row
```

The `__init__.py` re-exports top-level laddercodec symbols + local clipboard utilities for convenience.

## Roles

**Lead (you):** High-level investigator. You read the user's results, decide what to try next, and run tests (`make test`). For codec changes, direct the user to the laddercodec repo. For capture workflow changes, edit files in this directory.

**Assistant (subagent):** Scut work. Binary diffing, byte-level analysis, building verify queue entries, generating patch payloads, narrowing isolation batches. Give them a self-contained prompt. They should read `AGENTS.md` and `laddercodec/encode.py` (in the laddercodec repo) first.

## How to delegate

Write a prompt block the user can paste to a separate Claude Code session. Include:
- What files to read first (`AGENTS.md`, `laddercodec/encode.py`, relevant captures)
- Specific byte-level tasks (diff two .bin files, check offsets, build patch payloads)
- What NOT to do (don't edit source, don't run verify, etc.)
- What to report back

## Key files

- `capture_cli.py` — CLI entry point for verify/prepare/complete workflows
- `capture_workflow.py` — Encode pipeline integration, clipboard round-trip, header seed management
- `capture_registry.py` — Scratchpad manifest: tracks captured .bin files, labels, verify results
- `clipboard.py` — Win32 clipboard read/write/clear
- `AGENTS.md` — Capture/verify CLI guide. Give this to assistants.

## Dependency

`laddercodec` is declared in `pyproject.toml` as an editable local dep:

```toml
[tool.uv.sources]
laddercodec = { path = "../laddercodec", editable = true }
```

Both repos must be sibling directories. Changes to laddercodec are immediately visible.

## Verify workflow

```bash
uv run clicknick-ladder-capture verify prepare --label <label>   # load clipboard
# User pastes in Click, copies back
uv run clicknick-ladder-capture verify complete                  # or: verify run
```

## Golden fixtures

25 byte-exact golden fixtures live in **laddercodec**: `tests/fixtures/ladder_captures/golden/`. Regenerate with `uv run python scratchpad/generate_golden_fixtures.py` (from the laddercodec repo).

## Known limitations (not yet implemented in laddercodec)

- Styled comments (RTF bold/italic/underline)
- Contacts (NO, NC, edge, comparison, immediate variants)
- Coils / AF instructions (out, latch, reset)
- Instruction stream placement
