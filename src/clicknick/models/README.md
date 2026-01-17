# Models Module

This module contains the core data models and constants used throughout ClickNick.

## Overview

The models package defines the fundamental data structures that represent PLC addresses, nicknames, dataview rows, and block tags. All models are designed to be lightweight, with clear validation rules and state tracking.

## Core Components

### `constants.py`
Defines memory type ranges and configuration:
- `ADDRESS_RANGES` - Valid address ranges for each memory type (X, Y, C, T, TD, CT, CTD, SC, DS, DD, DH, DF, XD, YD, SD, TXT)
- `MEMORY_TYPE_BASES` - Base addresses for each memory type
- `DEFAULT_RETENTIVE` - Default retentive settings by memory type
- `DataType` enum - Data types for initial values (INT, FLOAT, HEX, BIN, ASCII)

### `address_row.py`
The `AddressRow` dataclass represents a single PLC address with nickname, comment, and metadata.

**Key Features:**
- **Dirty Tracking** - Automatically tracks changes to user-editable fields
- **Edit Session Locking** - User-editable fields raise `RuntimeError` if modified outside `SharedAddressData.edit_session()`
- **Validation** - Validates nickname and initial value on modification
- **Snapshot/Revert** - Can save original state and revert changes

**Fields:**
- **User-Editable (locked):** `nickname`, `comment`, `initial_value`, `retentive`
- **System Fields (free):** `used`, `validation_error`, `block_color`, etc.

**Edit Session Locking:**
User-editable fields can only be modified inside a `SharedAddressData.edit_session()` context. This enforces the unidirectional data flow pattern:

```python
# CORRECT - inside edit session
with shared_data.edit_session() as session:
    row.nickname = "NewName"  # OK
    session.mark_changed(row)

# INCORRECT - outside edit session
row.nickname = "NewName"  # RuntimeError!
```

**Usage Example:**
```python
row = AddressRow(
    address_key="X001",
    memory_type="X",
    index=1,
    nickname="StartButton",
    comment="Main start button"
)

# Check if modified
if row.is_dirty():
    print(f"Changed fields: {row.get_dirty_fields()}")

# Save changes
row.mark_saved()

# Revert changes
row.discard()
```

### `nickname.py`
The `Nickname` dataclass is a lightweight, immutable representation for autocomplete:

```python
@dataclass(frozen=True)
class Nickname:
    address: str        # e.g., "X001"
    nickname: str       # e.g., "StartButton"
    comment: str        # e.g., "Main start button"
    memory_type: str    # e.g., "X"
```

Used by `NicknameManager` to provide fast filtered autocomplete results.

### `dataview_row.py`
The `DataviewRow` dataclass represents a row in a CLICK DataView (.cdv) file:

```python
@dataclass
class DataviewRow:
    address: str
    format: str         # Display format (INT, FLOAT, HEX, etc.)
    label: str          # Display label
```

### `blocktag.py`
Contains BlockTag dataclass and utilities for parsing block tags from comments.

**BlockTag Structure:**
```python
@dataclass
class BlockTag:
    name: str                    # Block name
    is_opening: bool            # True for <Block>, False for </Block>
    is_self_closing: bool       # True for <Block />
    bg_color: str | None        # Background color (hex or keyword)
```

**Parsing Functions:**
- `parse_block_tag(comment: str) -> BlockTag | None` - Extract block tag from comment
- `match_block_tags(rows: list[AddressRow]) -> list[tuple[int, int, str]]` - Match opening/closing tags and return ranges

**Example:**
```python
tag = parse_block_tag("<Alarms bg='Red'>")
# BlockTag(name="Alarms", is_opening=True, is_self_closing=False, bg_color="Red")
```

### `validation.py`
Validation functions for nicknames and initial values:

**Nickname Validation:**
- Maximum 20 characters
- Allowed: letters, numbers, underscores
- Cannot start with a number
- Cannot be empty or whitespace-only

**Initial Value Validation:**
- Must match the specified `DataType` (INT, FLOAT, HEX, BIN, ASCII)
- Range checking based on memory type
- Format validation (e.g., hex must be valid hex digits)

**Functions:**
```python
def validate_nickname(nickname: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message)"""

def validate_initial_value(value: str, data_type: DataType, memory_type: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message)"""
```

### `address_utils.py`
Utilities for parsing and manipulating address strings:

**Functions:**
- `parse_address_key(address: str) -> tuple[str, int]` - Parse "X001" → ("X", 1)
- `format_address_key(memory_type: str, index: int) -> str` - Format ("X", 1) → "X001"
- `is_valid_address(address: str) -> bool` - Check if address is valid
- `get_address_range(memory_type: str) -> tuple[int, int]` - Get valid range for type

## Block Tag Specification

Block tags are XML-style tags added to the Comment field to create visual blocks in the Address Editor.

### Syntax

- `<BlockName>` – Opening tag for a range
- `</BlockName>` – Closing tag for a range
- `<BlockName />` – Self-closing tag for a single address
- `<BlockName bg="#color">` – Adds background color

### Colors

Colors can be specified as:
- **HEX codes:** `#FF5733`, `#3498DB`
- **Keywords:** Red, Pink, Purple, Deep Purple, Indigo, Blue, Light Blue, Cyan, Teal, Green, Light Green, Lime, Yellow, Amber, Orange, Deep Orange, Brown, Blue Grey

### Examples

**Simple Block:**
```
X001: <Alarms>              First alarm bit
X010: </Alarms>             Last alarm bit
```

**Block with Color:**
```
C001: <Counters bg="Blue">  Production counter
C020: </Counters>           Last counter
```

**Self-Closing Tag:**
```
DS1: <Config />             Configuration register
```

**Multiple Blocks:**
```
X001: <Inputs>
X010: <DoorSensors bg="Green">
X015: </DoorSensors>
X020: </Inputs>
```

### Visual Result

Addresses within block ranges are highlighted with the specified background color in the Address Editor. Nested blocks are supported, with the innermost block color taking precedence.

## Testing

Model tests are in `tests/test_models/`:
- `test_address_row.py` - Dirty tracking, validation, edit session locking
- `test_blocktag.py` - Tag parsing edge cases, color validation
- `test_validation.py` - Nickname and initial value validation rules
