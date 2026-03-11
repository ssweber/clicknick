# laddercodec Extraction Plan

Extract the pure-Python ladder encoder and CSV parser from clicknick into a
standalone package. MPL-2.0 licensed (protects RE work, compatible with both
pyrung MPL and clicknick AGPL).

## Why a separate package

- The encoder has **zero external dependencies** — no clicknick, no pyclickplc,
  no pywin32. Clean extraction boundary.
- Both pyrung and clicknick need it. Putting it in either one forces the other
  to take on a heavy transitive dependency.
- pyclickplc is MIT — wrong license for reverse-engineered binary format work.
- Small, focused package (~6 core files + CSV subpackage) — low maintenance.

## Package structure

```
laddercodec/
├── .github/workflows/ci.yml
├── pyproject.toml
├── Makefile
├── CLAUDE.md
├── src/laddercodec/
│   ├── __init__.py                   # public API
│   ├── encode.py                     # encode_rung()
│   ├── codec.py                      # ClickCodec (compile + encode + decode)
│   ├── decode.py                     # was legacy_codec.py
│   ├── model.py                      # Contact, Coil, RungGrid, InstructionType
│   ├── topology.py                   # wire parsing, cell offsets, constants
│   ├── empty_multirow.py             # scaffold synthesis
│   ├── resources/
│   │   ├── comment_phase_a.bin
│   │   └── empty_multirow_rule_minimal.scaffold.bin
│   └── csv/
│       ├── __init__.py
│       ├── ast.py
│       ├── contract.py
│       ├── shorthand.py
│       ├── token_parser.py
│       ├── parser.py
│       ├── bundle.py
│       └── adapter.py
├── tests/
│   ├── test_encode.py
│   ├── fixtures/ladder_captures/golden/   # 25 golden .bin files
│   └── ...
└── docs/
    ├── DEFINITIONS.md
    └── STATUS.md
```

## File mapping (clicknick → laddercodec)

### Moves (pure Python, zero deps)

| clicknick source                     | laddercodec destination        | Notes                    |
|--------------------------------------|----------------------------------|--------------------------|
| `ladder/encode.py`                   | `encode.py`                      | as-is                    |
| `ladder/codec.py`                    | `codec.py`                       | remove `legacy_fallback` |
| `ladder/legacy_codec.py`             | `decode.py`                      | rename                   |
| `ladder/model.py`                    | `model.py`                       | as-is                    |
| `ladder/topology.py`                 | `topology.py`                    | as-is                    |
| `ladder/empty_multirow.py`           | `empty_multirow.py`              | as-is                    |
| `ladder/resources/comment_phase_a.bin` | `resources/comment_phase_a.bin` | as-is                    |
| `ladder/resources/empty_multirow_rule_minimal.scaffold.bin` | `resources/...` | as-is         |
| `csv/__init__.py`                    | `csv/__init__.py`                | as-is                    |
| `csv/ast.py`                         | `csv/ast.py`                     | as-is                    |
| `csv/contract.py`                    | `csv/contract.py`                | as-is                    |
| `csv/shorthand.py`                   | `csv/shorthand.py`               | as-is                    |
| `csv/token_parser.py`                | `csv/token_parser.py`            | as-is                    |
| `csv/parser.py`                      | `csv/parser.py`                  | as-is                    |
| `csv/bundle.py`                      | `csv/bundle.py`                  | as-is                    |
| `csv/adapter.py`                     | `csv/adapter.py`                 | as-is                    |

### Stays in clicknick (needs pywin32/pyclickplc/clicknick)

| File                      | Why it stays                                |
|---------------------------|---------------------------------------------|
| `ladder/clipboard.py`     | pywin32 (Win32 clipboard I/O)               |
| `ladder/capture_cli.py`   | CLI entry point, imports capture_workflow    |
| `ladder/capture_workflow.py` | pyclickplc, clicknick utils, clipboard   |
| `ladder/capture_registry.py` | workflow tooling                          |
| `ladder/CLAUDE.md`        | workflow docs for capture tooling            |
| `ladder/AGENTS.md`        | delegation guide for capture sessions        |

### Dropped (reference-only, not used in encode path)

- `ladder/resources/grcecr_empty_native_20260308.bin`
- `ladder/resources/smoke_simple_native.scaffold.bin`
- `ladder/resources/phase3_wireframe_band_templates_20260308.json`

## Cleanup during extraction

1. **Rename** `legacy_codec.py` → `decode.py` (name matches function)
2. **Remove** `legacy_fallback` parameter from codec.py (dead, silently ignored)
3. **Drop** 3 unused resource files from the new package
4. **Update** all relative imports: `from .encode` stays, `from ..csv.shorthand`
   becomes `from .csv.shorthand` (csv is now a sibling subpackage)

## Import changes in clicknick after extraction

clicknick adds `laddercodec` as a dependency. Remaining ladder/ files update:

```python
# capture_workflow.py (before)
from ..csv.shorthand import normalize_shorthand_row
from .codec import ClickCodec, HeaderSeed
from .topology import HEADER_ENTRY_BASE, cell_offset, ...

# capture_workflow.py (after)
from laddercodec.csv.shorthand import normalize_shorthand_row
from laddercodec import ClickCodec, HeaderSeed
from laddercodec.topology import HEADER_ENTRY_BASE, cell_offset, ...
```

clicknick's `ladder/__init__.py` can re-export from laddercodec for
backward compat during transition, then slim down later.

## pyproject.toml (key sections)

```toml
[project]
name = "laddercodec"
description = "Binary codec for AutomationDirect CLICK PLC ladder clipboard format"
license = "MPL-2.0"
requires-python = ">=3.11,<4.0"
dependencies = []   # zero deps

[tool.hatch.version]
source = "uv-dynamic-versioning"

[tool.hatch.build.targets.wheel]
packages = ["src/laddercodec"]
```

## What pyrung gains (future)

```python
# pyrung/click/tag_map.py
def to_binary(self, program: Program) -> bytes:
    """Encode program as Click clipboard binary."""
    from laddercodec import ClickCodec
    bundle = self.to_ladder(program)
    # bundle rows → shorthand → encode
    ...
```

laddercodec becomes an optional dependency of pyrung (extras group).

## Ecosystem after extraction

```
laddercodec  (MPL-2.0, zero deps)
  ├── encode/decode Click clipboard binary
  └── CSV shorthand parsing

pyclickplc  (MIT, zero deps)
  ├── addresses, banks, blocks
  ├── dataview, nicknames, validation
  └── modbus client/server

pyrung  (MPL-2.0, deps: pyclickplc, pyrsistent)
  ├── ladder DSL + simulator
  ├── to_ladder() → CSV rows
  └── to_binary() → clipboard bytes (via optional laddercodec)

clicknick  (AGPL-3.0, deps: pyclickplc, laddercodec, pywin32, ...)
  ├── GUI: address editor, overlay, tag browser
  ├── ladder/clipboard.py (Win32 glue)
  └── ladder/capture_*.py (test workflow)
```

## What NOT to do now

- Don't reorganize internal module structure beyond the rename — keep files 1:1
  for easy diffing
- Don't prefix internals with `_` yet — wait until API stabilizes after
  contacts/coils are implemented
- Don't merge csv/ into the top level — it's a distinct parsing concern
- Don't create the repo yet — this plan needs review first
