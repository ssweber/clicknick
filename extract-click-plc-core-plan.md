# pyclickplc Extraction Plan

Transition plan for extracting shared CLICK PLC format knowledge from ClickNick into a standalone `pyclickplc` package, consumed by both ClickNick (GUI) and pyrung (simulation engine).

---

## Target Package Layout

```
pyclickplc/
  __init__.py          # re-export public API
  banks.py             # ADDRESS_RANGES, MEMORY_TYPE_BASES, DataType, defaults
  addresses.py         # AddressRecord, get_addr_key, parse/format helpers
  blocks.py            # BlockTag, BlockRange, MemoryBankMeta, parse/compute
  nicknames.py         # read/write CSV, type code mappings
  validation.py        # NICKNAME_MAX_LENGTH, FORBIDDEN_CHARS, validate_nickname()
```

---

## Phase 0: Simplify Block Tags in ClickNick (Before Extraction) - DONE

Do this work in ClickNick first. Extracting clean code is easier than extracting complex code and simplifying it after.

### 0a. Enforce unique block names

- Add validation: on block create/rename, check for duplicate names across all memory types
- Surface error in editor if duplicate detected
- Remove stack-per-`(memory_type, name)` logic from `compute_all_block_ranges` — simplify to plain dict lookup by name
- Remove memory_type scoping from `find_paired_tag_index` — unique names make it unnecessary

### 0b. Add auto-suffix for T/TD, CT/CTD

- Editor behavior: when user creates `<PumpTimers>` on T rows, auto-create `<PumpTimers_D>` on TD rows
- When user renames `<PumpTimers>` → `<CoolTimers>`, auto-rename `<PumpTimers_D>` → `<CoolTimers_D>`
- When user deletes `<PumpTimers>`, auto-delete `<PumpTimers_D>`
- `_D` suffix is convention only — pyclickplc treats them as two independent uniquely-named blocks; pairing is recognized by suffix match

### 0c. Move `compute_all_block_ranges` back to blocktag model

Move from `block_service.py` to `blocktag.py` (now simplified by unique names):

- `find_paired_tag_index` — dict scan by name, no depth tracking
- `find_block_range_indices` — thin wrapper
- `validate_block_span` — format constraint
- `compute_all_block_ranges` — simple open/close matching by unique name

Keep in `BlockService` (ClickNick editor coordination):

- `update_colors` — mutates AddressStore
- `auto_update_matching_block_tag` — editor auto-sync UX
- `apply_block_tag` — auto-suffix editor behavior
- `compute_block_colors_map` — UI rendering helper

---

## Phase 1: Extract `banks.py` and `addresses.py`

Lowest risk. Pure data and pure functions with zero behavioral change.

### banks.py — from `constants.py`

Move:

| Source (`constants.py`)       | Destination (`banks.py`)       |
|-------------------------------|-------------------------------|
| `ADDRESS_RANGES`              | `ADDRESS_RANGES`              |
| `MEMORY_TYPE_BASES`           | `MEMORY_TYPE_BASES`           |
| `_INDEX_TO_TYPE`              | `_INDEX_TO_TYPE`              |
| `DataType` enum               | `DataType`                    |
| `DATA_TYPE_DISPLAY`           | `DATA_TYPE_DISPLAY`           |
| `DATA_TYPE_HINTS`             | `DATA_TYPE_HINTS`             |
| `MEMORY_TYPE_TO_DATA_TYPE`    | `MEMORY_TYPE_TO_DATA_TYPE`    |
| `DEFAULT_RETENTIVE`           | `DEFAULT_RETENTIVE`           |
| `INTERLEAVED_PAIRS`           | `INTERLEAVED_PAIRS`           |
| `INTERLEAVED_TYPE_PAIRS`      | `INTERLEAVED_TYPE_PAIRS`      |
| `BIT_ONLY_TYPES`              | `BIT_ONLY_TYPES`              |

Keep in ClickNick `constants.py` (GUI-specific):

- `NON_EDITABLE_TYPES`
- `PAIRED_RETENTIVE_TYPES` (editor behavior for retentive sync)

Update ClickNick: `from pyclickplc.banks import ADDRESS_RANGES, DataType, ...`

### addresses.py — from `address_row.py`

Move:

| Source (`address_row.py`)        | Destination (`addresses.py`)     |
|----------------------------------|----------------------------------|
| `get_addr_key`                   | `get_addr_key`                   |
| `parse_addr_key`                 | `parse_addr_key`                 |
| `format_address_display`         | `format_address_display`         |
| `parse_address_display`          | `parse_address_display`          |
| `normalize_address`              | `normalize_address`              |
| `is_xd_yd_upper_byte`           | `is_xd_yd_upper_byte`           |
| `is_xd_yd_hidden_slot`          | `is_xd_yd_hidden_slot`          |
| `xd_yd_mdb_to_display`          | `xd_yd_mdb_to_display`          |
| `xd_yd_display_to_mdb`          | `xd_yd_display_to_mdb`          |

New in `addresses.py`:

```python
@dataclass(frozen=True)
class AddressRecord:
    """Minimal address representation shared between consumers."""
    memory_type: str
    address: int
    nickname: str = ""
    comment: str = ""
    initial_value: str = ""
    retentive: bool = False
    data_type: int = DataType.BIT

    @property
    def addr_key(self) -> int:
        return get_addr_key(self.memory_type, self.address)

    @property
    def display_address(self) -> str:
        return format_address_display(self.memory_type, self.address)
```

Keep in ClickNick `address_row.py`:

- `AddressRow` (adds validation state, GUI display, editor helpers)
- `AddressRow.from_record(r: AddressRecord)` class method (new, adapter)

---

## Phase 2: Extract `blocks.py`

Move block tag model from ClickNick's `blocktag.py` (post Phase 0 simplification).

### blocks.py — from `blocktag.py`

Move:

| Source (`blocktag.py`)              | Destination (`blocks.py`)           |
|-------------------------------------|-------------------------------------|
| `HasComment` protocol               | `HasComment`                        |
| `BlockTag` dataclass                | `BlockTag`                          |
| `BlockRange` dataclass              | `BlockRange`                        |
| `parse_block_tag`                   | `parse_block_tag`                   |
| `format_block_tag`                  | `format_block_tag`                  |
| `extract_block_name`                | `extract_block_name`                |
| `strip_block_tag`                   | `strip_block_tag`                   |
| `get_block_type`                    | `get_block_type`                    |
| `is_block_tag`                      | `is_block_tag`                      |
| `_extract_bg_attribute`             | `_extract_bg_attribute`             |
| `_is_valid_tag_name`                | `_is_valid_tag_name`                |
| `_try_parse_tag_at`                 | `_try_parse_tag_at`                 |
| `find_paired_tag_index`             | `find_paired_tag_index`             |
| `find_block_range_indices`          | `find_block_range_indices`          |
| `compute_all_block_ranges`          | `compute_all_block_ranges`          |
| `validate_block_span`               | `validate_block_span`               |

New in `blocks.py`:

```python
@dataclass(frozen=True)
class MemoryBankMeta:
    """Metadata for a memory bank discovered from block tags."""
    name: str
    memory_type: str
    start_address: int        # hardware address
    end_address: int          # hardware address, inclusive
    data_type: int
    retentive: bool
    bg_color: str | None = None
    paired_bank: str | None = None  # recognized by _D suffix convention

def extract_bank_metas(
    records: list[AddressRecord],
) -> dict[str, MemoryBankMeta]:
    """Compute MemoryBankMetas from address records using block tags.

    Discovers block tag pairs, extracts address ranges and types,
    recognizes _D suffix pairing for timer/counter banks.

    Returns:
        Dict mapping block name to MemoryBankMeta
    """
    ...
```

Keep in ClickNick `block_service.py`:

- `BlockService.update_colors`
- `BlockService.auto_update_matching_block_tag`
- `BlockService.apply_block_tag`
- `BlockService.compute_block_colors_map`

These import parsing functions from `clickplc.blocks` instead of `blocktag.py`.

---

## Phase 3: Extract `nicknames.py` and `validation.py`

### nicknames.py — from `data_source.py`

Move:

| Source (`data_source.py`)            | Destination (`nicknames.py`)         |
|--------------------------------------|--------------------------------------|
| `CSV_COLUMNS`                        | `CSV_COLUMNS`                        |
| `DATA_TYPE_STR_TO_CODE`             | `DATA_TYPE_STR_TO_CODE`             |
| `DATA_TYPE_CODE_TO_STR`             | `DATA_TYPE_CODE_TO_STR`             |
| `ADDRESS_PATTERN`                    | `ADDRESS_PATTERN`                    |
| `load_addresses_from_mdb_dump`       | `read_mdb_csv` (rename)             |
| CSV read logic from `CsvDataSource`  | `read_csv`                           |
| CSV write logic from `CsvDataSource` | `write_csv`                          |
| `convert_mdb_csv_to_user_csv`        | `convert_mdb_csv_to_user_csv`       |

Public API:

```python
def read_csv(path: str) -> dict[int, AddressRecord]:
    """Read CLICK user-format CSV. Returns addr_key -> AddressRecord."""
    ...

def read_mdb_csv(path: str) -> dict[int, AddressRecord]:
    """Read CLICK Address.csv (MDB export format). Returns addr_key -> AddressRecord."""
    ...

def write_csv(path: str, records: Iterable[AddressRecord]) -> int:
    """Write user-format CSV. Returns number of records written."""
    ...

def load_nickname_file(path: str) -> NicknameProject:
    """High-level loader: reads CSV, extracts block tags, builds bank metas.

    Returns:
        NicknameProject with records, banks, and standalone tags
    """
    ...

@dataclass
class NicknameProject:
    records: dict[int, AddressRecord]          # all records
    banks: dict[str, MemoryBankMeta]           # discovered from block tags
    tags: dict[str, AddressRecord]             # not in any block
```

Keep in ClickNick `data_source.py`:

- `DataSource` ABC
- `CsvDataSource` — becomes thin adapter:

```python
class CsvDataSource(DataSource):
    def load_all_addresses(self) -> dict[int, AddressRow]:
        records = clickplc.read_csv(self._csv_path)
        return {k: AddressRow.from_record(r) for k, r in records.items()}

    def save_changes(self, rows: Sequence[AddressRow]) -> int:
        records = [r.to_record() for r in rows if r.has_content]
        return clickplc.write_csv(self._csv_path, records)
```

- `MdbDataSource` — unchanged, stays entirely in ClickNick

### validation.py — from `constants.py`

Move:

| Source (`constants.py`)           | Destination (`validation.py`)     |
|-----------------------------------|-----------------------------------|
| `NICKNAME_MAX_LENGTH`             | `NICKNAME_MAX_LENGTH`             |
| `COMMENT_MAX_LENGTH`              | `COMMENT_MAX_LENGTH`              |
| `FORBIDDEN_CHARS`                 | `FORBIDDEN_CHARS`                 |
| `RESERVED_NICKNAMES`              | `RESERVED_NICKNAMES`              |
| `INT_MIN/MAX, INT2_MIN/MAX, ...`  | Numeric range constants           |

New:

```python
def validate_nickname(name: str) -> tuple[bool, str | None]:
    """Validate a nickname against CLICK rules. Returns (valid, error)."""
    ...

def validate_initial_value(value: str, data_type: int) -> tuple[bool, str | None]:
    """Validate an initial value for the given data type. Returns (valid, error)."""
    ...
```

---

## Phase 4: Update ClickNick Imports

Mechanical find-and-replace across ClickNick:

```python
# Before
from ..models.constants import ADDRESS_RANGES, DataType, ...
from ..models.address_row import get_addr_key, parse_addr_key, ...
from ..models.blocktag import parse_block_tag, BlockTag, ...

# After
from pyclickplc.banks import ADDRESS_RANGES, DataType, ...
from pyclickplc.addresses import get_addr_key, parse_addr_key, AddressRecord
from pyclickplc.blocks import parse_block_tag, BlockTag, ...
from pyclickplc.nicknames import read_csv, write_csv
from pyclickplc.validation import validate_nickname, NICKNAME_MAX_LENGTH, ...
```

Delete moved code from ClickNick. What remains in each file:

| ClickNick file          | Remaining content                                    |
|-------------------------|------------------------------------------------------|
| `constants.py`          | `NON_EDITABLE_TYPES`, `PAIRED_RETENTIVE_TYPES`      |
| `address_row.py`        | `AddressRow` (GUI model), `from_record`, `to_record` |
| `blocktag.py`           | Empty or deleted (re-exports from pyclickplc if needed)|
| `block_service.py`      | `BlockService` (editor coordination only)            |
| `data_source.py`        | `DataSource` ABC, `CsvDataSource` (thin), `MdbDataSource` |

---

## Phase 5: Wire into pyrung

With pyclickplc published:

```python
# pyrung/click/__init__.py
from pyclickplc.banks import ADDRESS_RANGES, DataType, DEFAULT_RETENTIVE
from pyclickplc.addresses import AddressRecord
from pyclickplc.blocks import MemoryBankMeta
from pyclickplc.nicknames import load_nickname_file

# Pre-built banks constructed from pyclickplc data
X = MemoryBank("X", TagType.BOOL, range(1, ADDRESS_RANGES["X"][1] + 1), retentive=False)
DS = MemoryBank("DS", TagType.INT, range(1, ADDRESS_RANGES["DS"][1] + 1), retentive=True)
# etc.
```

```python
# pyrung TagMap integration
class TagMap:
    @classmethod
    def from_nickname_file(cls, path: str) -> "TagMap":
        project = load_nickname_file(path)
        mapping = {}
        for meta in project.banks.values():
            bank = MemoryBank.from_meta(meta)
            mapping[bank] = hardware_slice_from_meta(meta)
        for name, record in project.tags.items():
            tag = tag_from_record(record)
            mapping[tag] = hardware_address_from_record(record)
        return cls(mapping)
```

---

## Future (Not This Plan)

- Mutation API in pyclickplc: `add_block_tag`, `rename_block_tag`, `delete_block_tag`
- Nickname CSV export from pyrung (round-trip: pyrung → CSV → ClickNick → hardware)
- `from_nickname_file()` nickname export (generate CSV from TagMap)
- Click nickname file format changes (if Automation Direct updates)
