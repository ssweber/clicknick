"""ClickCodec — translates RungGrid to/from clipboard bytes.

Template-based: loads a known-good capture and patches instruction-specific
fields at known offsets. No Construct dependency.
"""

from __future__ import annotations

from importlib import resources

from .model import Coil, Contact, InstructionType, RungGrid

BUFFER_SIZE = 8192  # 0x2000 — fixed clipboard size
CELL_SIZE = 0x40  # 64 bytes per cell
COLS_PER_ROW = 32  # A(0) through AF(31)
ROW_STARTS = {0: 0x0A60, 1: 0x1260}

_template_cache: bytes | None = None


def _load_template() -> bytes:
    global _template_cache
    if _template_cache is None:
        _template_cache = (
            resources.files("clicknick.ladder.resources")
            .joinpath("NO_X002_coil.AF.bin")
            .read_bytes()
        )
        assert len(_template_cache) == BUFFER_SIZE
    return _template_cache


def _encode_operand(operand: str, expected_len: int = 4) -> bytes:
    """Encode operand string as UTF-16LE."""
    assert len(operand) == expected_len, f"Operand {operand!r} must be {expected_len} chars"
    return operand.encode("utf-16-le")


def _decode_operand(data: bytes) -> str:
    """Decode UTF-16LE operand string."""
    return data.decode("utf-16-le").rstrip("\x00")


def _encode_func_code(code: str) -> bytes:
    """Encode function code string as UTF-16LE."""
    return code.encode("utf-16-le")


class ClickCodec:
    """Translates RungGrid <-> 8192-byte clipboard buffer.

    Template patching at known offsets. The Offsets inner class is
    the single source of truth for all patch points.
    """

    class Offsets:
        """All patch points in one place. Derived from cell structure findings."""

        # Contact instruction (Row 0, Cells A-B)
        CONTACT_TYPE_ID = ROW_STARTS[0] + 0 * CELL_SIZE + 0x39
        CONTACT_OPERAND = ROW_STARTS[0] + 1 * CELL_SIZE + 0x09
        CONTACT_FUNC_CODE = ROW_STARTS[0] + 1 * CELL_SIZE + 0x23

        # Coil instruction (Row 1, Cells A-B)
        COIL_TYPE_ID = ROW_STARTS[1] + 0 * CELL_SIZE + 0x32
        COIL_OPERAND = ROW_STARTS[1] + 1 * CELL_SIZE + 0x02
        COIL_FUNC_CODE = ROW_STARTS[1] + 1 * CELL_SIZE + 0x2E

        # Nickname (Row 1, Col C area)
        NICKNAME_FLAG = 0x12F0
        NICKNAME_STRING = 0x12F4
        NICKNAME_MAX_CHARS = 8

        # Sizes
        OPERAND_CHARS = 4  # chars (8 bytes UTF-16LE)
        FUNC_CODE_CHARS = 4

    def _patch_nickname(self, buf: bytearray, nickname: str) -> None:
        """Patch nickname into buffer. Handles structural flag shifting."""
        off = self.Offsets
        nn_encoded = nickname.encode("utf-16-le")
        nn_len = len(nn_encoded)

        buf[off.NICKNAME_FLAG] = 0x01

        # Structural flags at +5 and +8 from NICKNAME_STRING shift
        # right by the nickname byte length
        flag_offsets = (5, 8)  # relative to NICKNAME_STRING
        clear_end = nn_len + max(flag_offsets) + 4  # margin

        buf[off.NICKNAME_STRING : off.NICKNAME_STRING + clear_end] = b"\x00" * clear_end
        buf[off.NICKNAME_STRING : off.NICKNAME_STRING + nn_len] = nn_encoded

        for rel in flag_offsets:
            buf[off.NICKNAME_STRING + rel + nn_len] = 0x01

    def encode(self, grid: RungGrid) -> bytes:
        """RungGrid -> 8192-byte clipboard buffer."""
        buf = bytearray(_load_template())
        off = self.Offsets

        # Contact type ID (low byte; high byte 0x27 stays from template)
        buf[off.CONTACT_TYPE_ID] = grid.contact.type.value

        # Contact operand
        op = _encode_operand(grid.contact.operand, off.OPERAND_CHARS)
        buf[off.CONTACT_OPERAND : off.CONTACT_OPERAND + len(op)] = op

        # Contact function code
        fc = _encode_func_code(grid.contact.func_code)
        buf[off.CONTACT_FUNC_CODE : off.CONTACT_FUNC_CODE + len(fc)] = fc

        # Coil type ID
        buf[off.COIL_TYPE_ID] = grid.coil.type.value

        # Coil operand
        cop = _encode_operand(grid.coil.operand, off.OPERAND_CHARS)
        buf[off.COIL_OPERAND : off.COIL_OPERAND + len(cop)] = cop

        # Coil function code
        cfc = _encode_func_code(grid.coil.func_code)
        buf[off.COIL_FUNC_CODE : off.COIL_FUNC_CODE + len(cfc)] = cfc

        # Nickname
        if grid.nickname:
            self._patch_nickname(buf, grid.nickname)

        return bytes(buf)

    def decode(self, data: bytes) -> RungGrid:
        """8192-byte clipboard buffer -> RungGrid."""
        assert len(data) == BUFFER_SIZE
        off = self.Offsets

        # Contact
        type_byte = data[off.CONTACT_TYPE_ID]
        contact_type = InstructionType(type_byte)
        contact_op = _decode_operand(
            data[off.CONTACT_OPERAND : off.CONTACT_OPERAND + off.OPERAND_CHARS * 2]
        )
        contact = Contact(type=contact_type, operand=contact_op)

        # Coil
        coil_type_byte = data[off.COIL_TYPE_ID]
        coil_type = InstructionType(coil_type_byte)
        coil_op = _decode_operand(data[off.COIL_OPERAND : off.COIL_OPERAND + off.OPERAND_CHARS * 2])
        coil = Coil(type=coil_type, operand=coil_op)

        # Nickname
        nickname = None
        if data[off.NICKNAME_FLAG] == 0x01:
            nn_raw = data[off.NICKNAME_STRING : off.NICKNAME_STRING + off.NICKNAME_MAX_CHARS * 2]
            nickname = nn_raw.decode("utf-16-le").split("\x00")[0] or None

        return RungGrid(contact=contact, coil=coil, nickname=nickname)
