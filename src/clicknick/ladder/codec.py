"""ClickCodec — translates RungGrid to/from clipboard bytes.

Single-scaffold encoder:
- Starts from one canonical scaffold capture (`smoke_simple_native`)
- Patches semantic regions (header row/class, instruction streams, nickname)
- Avoids per-shape runtime templates
"""

from __future__ import annotations

from importlib import resources
from typing import Final

from .model import (
    COIL_FUNC_CODES,
    CONTACT_FUNC_CODES,
    OPERAND_RE,
    Coil,
    Contact,
    InstructionType,
    RungGrid,
)
from .topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    HEADER_ENTRY_BASE,
    HEADER_ROW_CLASS_OFFSET,
    WireTopology,
    cell_offset,
    parse_wire_topology,
)

BUFFER_SIZE = 8192  # 0x2000 — fixed clipboard size
CELL_SIZE = 0x40  # 64 bytes per cell
COLS_PER_ROW = 32  # A(0) through AF(31)
ROW_STARTS = {0: 0x0A60, 1: 0x1260}
GRID_START = min(ROW_STARTS.values())
GRID_END = max(ROW_STARTS.values()) + COLS_PER_ROW * CELL_SIZE

ROW_CLASS_BY_COUNT: Final[dict[int, int]] = {
    1: 0x40,
    2: 0x60,
    3: 0x80,
}

_scaffold_cache: bytes | None = None

CONTACT_CODE_TO_FLAGS: Final[dict[str, tuple[InstructionType, bool]]] = {
    code: (itype, immediate) for (itype, immediate), code in CONTACT_FUNC_CODES.items()
}
CONTACT_CODE_TO_FLAGS.update(
    {
        "4101": (InstructionType.CONTACT_EDGE, False),
        "4102": (InstructionType.CONTACT_EDGE, False),
    }
)

COIL_CODE_TO_FLAGS: Final[dict[str, tuple[InstructionType, bool, bool]]] = {
    code: (itype, is_range, immediate)
    for (itype, is_range, immediate), code in COIL_FUNC_CODES.items()
}

# Type+2..type+15 stream prefixes seen in captures.
_CONTACT_PREFIX: Final[bytes] = bytes.fromhex("00000100040000006560FFFFFFFF")
_COIL_PREFIX: Final[bytes] = bytes.fromhex("00000100060000006660FFFFFFFF")

# Stream fragments observed around operands/function code blocks.
_BLOCK_AFTER_CONTACT_OP: Final[bytes] = bytes.fromhex("0000F511FFFFFFFF")
_BLOCK_AFTER_COIL_OP: Final[bytes] = bytes.fromhex("00006760FFFFFFFF")
_BLOCK_F8: Final[bytes] = bytes.fromhex("0000F811FFFFFFFF")
_BLOCK_F5: Final[bytes] = bytes.fromhex("30000000F511FFFFFFFF")
_FUNC_PRE_NORMAL: Final[bytes] = bytes.fromhex("300000001832FFFFFFFF")
_FUNC_PRE_IMMEDIATE: Final[bytes] = bytes.fromhex("2D00310000001832FFFFFFFF")
_FUNC_POST: Final[bytes] = bytes.fromhex("00000000FFFFFFFF")
_BASE_CONTACT_STREAM_LEN: Final[int] = 58  # X001 non-immediate in scaffold baseline
_CELL_CONTROL_A_OFFSET: Final[int] = 0x1A
_CELL_CONTROL_B_OFFSET: Final[int] = 0x1B
_CELL_PROFILE_05_OFFSET: Final[int] = 0x05
_CELL_PROFILE_11_OFFSET: Final[int] = 0x11


def _load_scaffold() -> bytes:
    global _scaffold_cache
    if _scaffold_cache is None:
        _scaffold_cache = (
            resources.files("clicknick.ladder")
            .joinpath("resources/smoke_simple_native.scaffold.bin")
            .read_bytes()
        )
        assert len(_scaffold_cache) == BUFFER_SIZE
    return _scaffold_cache


def _encode_utf16(value: str) -> bytes:
    return value.encode("utf-16-le")


def _read_utf16_ascii(data: bytes, offset: int, max_chars: int = 8) -> str | None:
    chars: list[str] = []
    for i in range(max_chars):
        pos = offset + i * 2
        if pos + 1 >= len(data):
            break
        c = data[pos] | (data[pos + 1] << 8)
        if c == 0:
            break
        if not (0x20 <= c < 0x7F):
            return None
        chars.append(chr(c))
    return "".join(chars) if chars else None


def _scan_type_offsets(data: bytes) -> list[int]:
    offsets: list[int] = []
    for i in range(GRID_START, min(len(data), GRID_END) - 1):
        if data[i + 1] == 0x27 and data[i] != 0x00:
            offsets.append(i)
    return offsets


def _decode_func_code_at(data: bytes, offset: int) -> str | None:
    raw = _read_utf16_ascii(data, offset, max_chars=4)
    if raw and len(raw) == 4 and raw.isdigit():
        return raw
    return None


def _find_func_code(
    data: bytes, type_offset: int, deltas: list[int], known: set[str]
) -> tuple[int, str]:
    seen: set[int] = set()
    for delta in deltas:
        if delta in seen:
            continue
        seen.add(delta)
        code = _decode_func_code_at(data, type_offset + delta)
        if code in known:
            return delta, code
    raise ValueError(f"Could not locate known function code near type offset 0x{type_offset:04X}")


def _canonicalize_operand_for_encoding(operand: str) -> str:
    """Canonicalize operand representation to match Click native stream forms.

    Click encodes X/Y addresses as 3-digit decimals (e.g. X1 -> X001).
    Other banks are kept as-is.
    """
    idx = 0
    while idx < len(operand) and operand[idx].isalpha():
        idx += 1
    if idx == 0 or idx == len(operand):
        return operand
    prefix = operand[:idx]
    digits = operand[idx:]
    if prefix in {"X", "Y"} and digits.isdigit():
        return f"{prefix}{int(digits):03d}"
    return operand


def _build_contact_stream(contact: Contact) -> bytes:
    op = _encode_utf16(_canonicalize_operand_for_encoding(contact.operand))
    pre = _FUNC_PRE_IMMEDIATE if contact.immediate else _FUNC_PRE_NORMAL
    func = _encode_utf16(contact.func_code)
    return (
        bytes((contact.type.value, 0x27))
        + _CONTACT_PREFIX
        + op
        + _BLOCK_AFTER_CONTACT_OP
        + pre
        + func
        + _FUNC_POST
    )


def _build_coil_stream(coil: Coil) -> bytes:
    op1 = _encode_utf16(_canonicalize_operand_for_encoding(coil.operand))
    pre = _FUNC_PRE_IMMEDIATE if coil.immediate else _FUNC_PRE_NORMAL
    func = _encode_utf16(coil.func_code)
    parts = [
        bytes((coil.type.value, 0x27)),
        _COIL_PREFIX,
        op1,
        _BLOCK_AFTER_COIL_OP,
    ]
    if coil.range_end is not None:
        parts.append(_encode_utf16(_canonicalize_operand_for_encoding(coil.range_end)))
    parts.extend([_BLOCK_F8, _BLOCK_F5, pre, func, _FUNC_POST])
    return b"".join(parts)


def _decode_contact_at(data: bytes, contact_offset: int) -> Contact:
    contact_type = InstructionType(data[contact_offset])
    if contact_type not in (
        InstructionType.CONTACT_NO,
        InstructionType.CONTACT_NC,
        InstructionType.CONTACT_EDGE,
    ):
        raise ValueError(f"Unsupported contact type 0x27{data[contact_offset]:02X}")

    contact_op = _read_utf16_ascii(data, contact_offset + 16)
    if not contact_op or not OPERAND_RE.fullmatch(contact_op):
        raise ValueError("Could not decode valid contact operand")

    contact_base = 34 + len(contact_op) * 2
    _, contact_code = _find_func_code(
        data,
        contact_offset,
        [contact_base, contact_base + 2] + list(range(34, 50, 2)),
        set(CONTACT_CODE_TO_FLAGS),
    )
    code_type, contact_immediate = CONTACT_CODE_TO_FLAGS[contact_code]
    if code_type != contact_type:
        raise ValueError(
            f"Contact type mismatch: type 0x27{contact_type.value:02X}, func code {contact_code}"
        )

    edge_kind = None
    if contact_type == InstructionType.CONTACT_EDGE:
        edge_kind = "rise" if contact_code == "4101" else "fall"
    return Contact(
        type=contact_type,
        operand=contact_op,
        immediate=contact_immediate,
        edge_kind=edge_kind,
    )


def _decode_coil_at(data: bytes, coil_offset: int) -> Coil:
    coil_type = InstructionType(data[coil_offset])
    if coil_type not in (
        InstructionType.COIL_OUT,
        InstructionType.COIL_LATCH,
        InstructionType.COIL_RESET,
    ):
        raise ValueError(f"Unsupported coil type 0x27{data[coil_offset]:02X}")

    coil_op = _read_utf16_ascii(data, coil_offset + 16)
    if not coil_op or not OPERAND_RE.fullmatch(coil_op):
        raise ValueError("Could not decode valid coil operand")

    coil_base_normal = 52 + len(coil_op) * 2
    _, coil_code = _find_func_code(
        data,
        coil_offset,
        [coil_base_normal, coil_base_normal + 2] + list(range(52, 82, 2)),
        set(COIL_CODE_TO_FLAGS),
    )
    code_type, code_is_range, code_immediate = COIL_CODE_TO_FLAGS[coil_code]
    if code_type != coil_type:
        raise ValueError(
            f"Coil type mismatch: type 0x27{coil_type.value:02X}, func code {coil_code}"
        )

    range_end = None
    if code_is_range:
        op2_offset = coil_offset + 24 + len(coil_op) * 2
        op2 = _read_utf16_ascii(data, op2_offset)
        if not op2 or not OPERAND_RE.fullmatch(op2):
            raise ValueError("Coil range function code found, but range end operand missing")
        range_end = op2
    return Coil(type=coil_type, operand=coil_op, range_end=range_end, immediate=code_immediate)


def _row_class_for_count(row_count: int) -> int:
    return ROW_CLASS_BY_COUNT.get(row_count, ROW_CLASS_BY_COUNT[1])


def _new_buffer(*, row_count: int = 1) -> bytearray:
    """Build baseline 8192-byte clipboard payload from one canonical scaffold."""
    buf = bytearray(_load_scaffold())
    buf[0:8] = b"CLICK   "  # keep canonical magic fixed

    # Keep scaffold header entry constants and only patch logical row class.
    buf[HEADER_ENTRY_BASE + HEADER_ROW_CLASS_OFFSET] = _row_class_for_count(row_count)

    return buf


def _contact_stream_shift(contact: Contact) -> int:
    """Relative shift from scaffold baseline contact stream length."""
    probe = Contact(
        type=contact.type,
        operand=_canonicalize_operand_for_encoding(contact.operand),
        immediate=contact.immediate,
        edge_kind=contact.edge_kind,
    )
    return len(_build_contact_stream(probe)) - _BASE_CONTACT_STREAM_LEN


def _two_series_control_profile_bytes(first: Contact, second: Contact) -> tuple[int, int]:
    """Return the (0x1A, 0x1B) profile values for two-series wiring cells."""
    if first.type == InstructionType.CONTACT_EDGE or second.type == InstructionType.CONTACT_EDGE:
        return (0x00, 0x00)

    if first.immediate and second.immediate:
        return (0x00, 0xFF)

    if first.immediate or second.immediate:
        return (0xFF, 0xFF)

    return (0xFF, 0x01)


def _two_series_profile_05_11_bytes(first: Contact, second: Contact) -> tuple[int, int]:
    """Return the (+0x05, +0x11) profile bytes for two-series wiring cells."""
    if first.type == InstructionType.CONTACT_EDGE:
        if first.edge_kind == "rise":
            return (0x62, 0x01)
        if first.edge_kind == "fall":
            return (0x64, 0x01)
        return (0x00, 0x01)

    if first.immediate and not second.immediate:
        return (0x25, 0x52)

    if not first.immediate and second.immediate:
        return (0x04, 0x0C)

    # Includes both-immediate and fully non-immediate series profiles.
    return (0x00, 0x00)


def _write_topology_for_simple_series(buf: bytearray, contacts: list[Contact]) -> None:
    """Write row0 topology bytes for the simple series forms supported by RungGrid."""
    contact_count = len(contacts)
    if contact_count not in (1, 2):
        return

    # Do not mutate col1 topology bytes directly: for contact cells these offsets
    # sit inside instruction stream bytes and can corrupt operands/func codes.
    # We only force safe bytes outside instruction stream overlap.

    # col0: horizontal wire
    col0 = cell_offset(0, 0)
    buf[col0 + CELL_HORIZONTAL_LEFT_OFFSET] = 0x01
    buf[col0 + CELL_HORIZONTAL_RIGHT_OFFSET] = 0x01

    if contact_count == 2:
        first_contact, second_contact = contacts

        # Two-series capture pattern:
        # - col3 flags are emitted by stream bytes (do not overwrite)
        # - cols4..31 vary by contact family
        left_value = 0xFF
        right_value = 0x00

        if (
            first_contact.type == InstructionType.CONTACT_EDGE
            or second_contact.type == InstructionType.CONTACT_EDGE
        ):
            left_value = 0x01
            right_value = 0x01
        elif first_contact.immediate and second_contact.immediate:
            left_value = 0x00
            right_value = 0xFF
        elif first_contact.immediate or second_contact.immediate:
            left_value = 0xFF
            right_value = 0x01

        control_a, control_b = _two_series_control_profile_bytes(first_contact, second_contact)
        profile_05, profile_11 = _two_series_profile_05_11_bytes(first_contact, second_contact)
        for col in range(4, COLS_PER_ROW):
            start = cell_offset(0, col)
            buf[start + CELL_HORIZONTAL_LEFT_OFFSET] = left_value
            buf[start + CELL_HORIZONTAL_RIGHT_OFFSET] = right_value
            buf[start + _CELL_PROFILE_05_OFFSET] = profile_05
            buf[start + _CELL_PROFILE_11_OFFSET] = profile_11
            buf[start + _CELL_CONTROL_A_OFFSET] = control_a
            buf[start + _CELL_CONTROL_B_OFFSET] = control_b

        # Native two-series captures carry the same control profile at row1/col0.
        row1_col0 = cell_offset(1, 0)
        buf[row1_col0 + _CELL_PROFILE_05_OFFSET] = profile_05
        buf[row1_col0 + _CELL_PROFILE_11_OFFSET] = profile_11
        buf[row1_col0 + _CELL_CONTROL_A_OFFSET] = control_a
        buf[row1_col0 + _CELL_CONTROL_B_OFFSET] = control_b


def _shift_region(buf: bytearray, *, start: int, delta: int) -> None:
    """Shift buffer[start:] right/left by delta bytes in place, zero-filling vacated space."""
    if delta == 0:
        return
    if start < 0 or start >= len(buf):
        return

    tail = buf[start:]
    if delta > 0:
        if delta >= len(tail):
            buf[start:] = b"\x00" * len(tail)
            return
        shifted = b"\x00" * delta + tail[:-delta]
    else:
        d = -delta
        if d >= len(tail):
            buf[start:] = b"\x00" * len(tail)
            return
        shifted = tail[d:] + b"\x00" * d
    buf[start:] = shifted


def _patch_header_variant_bytes(
    buf: bytearray,
    *,
    contacts: list[Contact],
    coil: Coil,
) -> None:
    """Patch observed per-entry variant bytes in header table.

    Native captures show 0x05/0x01 for the strict baseline scaffold case only:
    single NO contact + non-immediate OUT coil + no range.
    Other supported instruction variants use 0x15/0x01.
    """
    first = contacts[0]
    is_baseline_simple_out = (
        len(contacts) == 1
        and first.type == InstructionType.CONTACT_NO
        and not first.immediate
        and first.edge_kind is None
        and coil.type == InstructionType.COIL_OUT
        and not coil.immediate
        and coil.range_end is None
    )

    is_second_immediate_two_series = (
        len(contacts) == 2 and not contacts[0].immediate and contacts[1].immediate
    )

    if is_baseline_simple_out:
        b17, b18 = (0x05, 0x01)
    elif is_second_immediate_two_series:
        # Native recaptures for the second-immediate series variant normalize
        # this family byte to 0x0D.
        b17, b18 = (0x0D, 0x01)
    else:
        b17, b18 = (0x15, 0x01)

    for col in range(COLS_PER_ROW):
        entry_start = HEADER_ENTRY_BASE + col * CELL_SIZE
        buf[entry_start + 0x17] = b17
        buf[entry_start + 0x18] = b18
        if is_second_immediate_two_series:
            # These bytes were previously treated as volatile, but in this
            # specific family they gate single-rung assembly in pasteback.
            buf[entry_start + 0x05] = 0x04
            buf[entry_start + 0x11] = 0x0B

    if is_second_immediate_two_series:
        # Trailing header-area profile byte mirrors entry +0x05 for this family.
        buf[0x0A59] = 0x04


def _contact_label_for_type(contact_type: InstructionType) -> str:
    if contact_type == InstructionType.CONTACT_NO:
        return "ContactNO"
    if contact_type == InstructionType.CONTACT_EDGE:
        return "ContactNO"
    return "ContactNC"


def _patch_two_series_structure(
    buf: bytearray,
    *,
    first_shift: int,
    second_shift: int,
    second_contact: Contact,
    second_type_offset: int,
) -> None:
    """Patch deterministic non-stream bytes seen in native two-series captures."""
    # Label immediately preceding the second contact type marker.
    label = _encode_utf16(_contact_label_for_type(second_contact.type)) + b"\x00\x00"
    label_start = second_type_offset - len(label)
    if label_start >= 0:
        buf[label_start:second_type_offset] = label

    # Two-series row0 carries horizontal span with 0xFF conventions.
    cell2 = cell_offset(0, 2)
    buf[cell2 + 0x12 : cell2 + 0x16] = b"\x02\x00\x00\x00"

    cell4 = cell_offset(0, 4)
    buf[cell4 + 0x02] = 0x01

    # Two-series row1/col3 metadata offsets shift with total contact stream expansion.
    total_shift = first_shift + second_shift
    row1_col3 = cell_offset(1, 3)
    for delta in (0, 2, 4):
        buf[row1_col3 + 0x11 + delta] = 0x00
        buf[row1_col3 + 0x15 + delta] = 0x00
        buf[row1_col3 + 0x1E + delta] = 0x00
        buf[row1_col3 + 0x27 + delta] = 0x00
        buf[row1_col3 + 0x2A + delta] = 0x00
    buf[row1_col3 + 0x11 + total_shift] = 0x03
    buf[row1_col3 + 0x15 + total_shift] = 0x02
    buf[row1_col3 + 0x1E + total_shift] = 0x01
    buf[row1_col3 + 0x27 + total_shift] = 0x01
    buf[row1_col3 + 0x2A + total_shift] = 0x01
    # Keep this metadata byte clear; native captures keep it at zero.
    buf[row1_col3 + 0x23] = 0x00

    # For the second-immediate two-series profile, row1/col1 carries stable
    # non-stream bytes that gate coil materialization in Click rendering.
    if first_shift == 0 and second_shift == 2:
        row0_col0 = cell_offset(0, 0)
        row0_col1 = cell_offset(0, 1)
        row0_col2 = cell_offset(0, 2)
        row0_col4 = cell_offset(0, 4)
        row1_col0 = cell_offset(1, 0)
        row1_col1 = cell_offset(1, 1)
        buf[row0_col0 + 0x05] = 0x0C
        buf[row0_col1 + 0x3E] = 0x04
        buf[row0_col2 + 0x0A] = 0x0C
        buf[row0_col2 + 0x12] = 0x01
        buf[row0_col4 + 0x02] = 0x00
        buf[row0_col4 + 0x04] = 0x01
        buf[row0_col4 + 0x05] = 0x04
        buf[row0_col4 + 0x11] = 0x0C
        buf[row1_col0 + 0x05] = 0x04
        buf[row1_col0 + 0x11] = 0x0C
        buf[row1_col1 + 0x05] = 0x04
        buf[row1_col1 + 0x11] = 0x0C
        buf[row1_col1 + 0x19] = 0x02


def _clear_stale_type_marker(buf: bytearray, type_offset: int) -> None:
    """Zero marker bytes at a known anchor if they currently look like 0x27XX."""
    if type_offset < 0 or type_offset + 1 >= len(buf):
        return
    if buf[type_offset + 1] == 0x27:
        buf[type_offset] = 0x00
        buf[type_offset + 1] = 0x00


class ClickCodec:
    """Translates RungGrid <-> 8192-byte clipboard buffer."""

    class Offsets:
        """Anchor offsets for instruction stream placement."""

        # Contact instruction (Row 0, Cells A-B)
        CONTACT_TYPE_ID = ROW_STARTS[0] + 0 * CELL_SIZE + 0x39
        CONTACT2_TYPE_ID = ROW_STARTS[0] + 0xBE

        # Coil instruction anchors
        COIL_TYPE_ID_BASE = ROW_STARTS[1] + 0 * CELL_SIZE + 0x32
        COIL_TYPE_ID_BASE_TWO_SERIES = ROW_STARTS[1] + 1 * CELL_SIZE + 0x37

        # Nickname area
        NICKNAME_FLAG = 0x12F0
        NICKNAME_STRING = 0x12F4
        NICKNAME_MAX_CHARS = 8

    def _patch_nickname(self, buf: bytearray, nickname: str) -> None:
        """Patch nickname into buffer. Handles structural flag shifting."""
        off = self.Offsets
        nn_encoded = nickname.encode("utf-16-le")
        nn_len = len(nn_encoded)

        buf[off.NICKNAME_FLAG] = 0x01

        # Structural flags at +5 and +8 from NICKNAME_STRING shift by nickname byte length.
        flag_offsets = (5, 8)
        clear_end = nn_len + max(flag_offsets) + 4

        buf[off.NICKNAME_STRING : off.NICKNAME_STRING + clear_end] = b"\x00" * clear_end
        buf[off.NICKNAME_STRING : off.NICKNAME_STRING + nn_len] = nn_encoded

        for rel in flag_offsets:
            buf[off.NICKNAME_STRING + rel + nn_len] = 0x01

    def encode(self, grid: RungGrid) -> bytes:
        """RungGrid -> 8192-byte clipboard buffer."""
        off = self.Offsets
        contacts = grid.contacts
        if len(contacts) not in (1, 2):
            raise ValueError("Only 1 or 2 series contacts are currently supported")

        buf = _new_buffer(row_count=1)
        _patch_header_variant_bytes(
            buf,
            contacts=contacts,
            coil=grid.coil,
        )

        # Clear scaffold markers that can become stale when stream anchors move.
        _clear_stale_type_marker(buf, off.CONTACT2_TYPE_ID)
        _clear_stale_type_marker(buf, off.COIL_TYPE_ID_BASE)
        _clear_stale_type_marker(buf, off.COIL_TYPE_ID_BASE_TWO_SERIES)

        first_contact = contacts[0]
        first_shift = _contact_stream_shift(first_contact)
        edge_shift = -0x0A if first_contact.type == InstructionType.CONTACT_EDGE else 0
        first_type_offset = off.CONTACT_TYPE_ID + edge_shift
        # Single-contact immediate uses a +2 stream expansion that shifts a large
        # downstream region in native captures.
        if len(contacts) == 1 and first_shift > 0:
            _shift_region(buf, start=first_type_offset + 0x1F, delta=first_shift)
        first_stream = _build_contact_stream(first_contact)
        buf[first_type_offset : first_type_offset + len(first_stream)] = first_stream

        if len(contacts) == 1:
            coil_start = off.COIL_TYPE_ID_BASE + first_shift + edge_shift
        else:
            second_contact = contacts[1]
            second_shift = _contact_stream_shift(second_contact)
            second_start = off.CONTACT2_TYPE_ID + first_shift + edge_shift
            coil_start = off.COIL_TYPE_ID_BASE_TWO_SERIES + first_shift + second_shift + edge_shift
            base_coil_after_first = off.COIL_TYPE_ID_BASE + first_shift + edge_shift

            # Two-series captures shift the remainder of the stream/tail by the
            # gap between single-contact and two-series coil anchors.
            _shift_region(buf, start=second_start, delta=coil_start - base_coil_after_first)

            second_stream = _build_contact_stream(second_contact)
            buf[second_start : second_start + len(second_stream)] = second_stream
            _patch_two_series_structure(
                buf,
                first_shift=first_shift,
                second_shift=second_shift,
                second_contact=second_contact,
                second_type_offset=second_start,
            )

        coil_stream = _build_coil_stream(grid.coil)
        buf[coil_start : coil_start + len(coil_stream)] = coil_stream

        # Rewrite canonical row0 topology after byte shifts.
        _write_topology_for_simple_series(buf, contacts)

        if grid.nickname:
            self._patch_nickname(buf, grid.nickname)

        return bytes(buf)

    def decode(self, data: bytes) -> RungGrid:
        """8192-byte clipboard buffer -> RungGrid."""
        assert len(data) == BUFFER_SIZE
        off = self.Offsets

        type_offsets = _scan_type_offsets(data)
        if len(type_offsets) < 2:
            raise ValueError("Could not locate instruction type markers in buffer")

        contacts: list[Contact] = []
        coil: Coil | None = None
        last_contact_offset: int | None = None
        for type_offset in type_offsets:
            try:
                i_type = InstructionType(data[type_offset])
            except ValueError:
                continue

            if i_type in (
                InstructionType.CONTACT_NO,
                InstructionType.CONTACT_NC,
                InstructionType.CONTACT_EDGE,
            ):
                candidate = _decode_contact_at(data, type_offset)
                if (
                    contacts
                    and last_contact_offset is not None
                    and type_offset - last_contact_offset == CELL_SIZE
                    and candidate == contacts[-1]
                ):
                    continue
                contacts.append(candidate)
                last_contact_offset = type_offset
                continue

            if i_type in (
                InstructionType.COIL_OUT,
                InstructionType.COIL_LATCH,
                InstructionType.COIL_RESET,
            ):
                coil = _decode_coil_at(data, type_offset)
                break

        if not contacts:
            raise ValueError("Could not decode any contact instructions")
        if coil is None:
            raise ValueError("Could not decode coil instruction")

        nickname = None
        if data[off.NICKNAME_FLAG] == 0x01:
            nn_raw = data[off.NICKNAME_STRING : off.NICKNAME_STRING + off.NICKNAME_MAX_CHARS * 2]
            nickname = nn_raw.decode("utf-16-le").split("\x00")[0] or None

        return RungGrid(
            contact=contacts[0],
            series_contacts=contacts[1:],
            coil=coil,
            nickname=nickname,
        )

    def decode_wire_topology(self, data: bytes) -> WireTopology:
        """Decode per-cell wire topology flags from clipboard bytes."""
        return parse_wire_topology(data)
