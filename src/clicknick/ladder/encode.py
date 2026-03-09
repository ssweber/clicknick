"""Ladder rung encoder — unified pipeline.

Definitions
-----------

Rung:
    One logical unit of ladder logic. A rung has 1..32 rows, each with
    31 condition columns (A..AE) and 1 output column (AF). The rung may
    also carry a single plain-text comment.

Row:
    A horizontal slice of the rung grid. Row 0 is the topmost visible
    row. The grid starts at absolute offset 0x0A60 with a stride of
    0x800 per row (32 columns x 64 bytes per cell).

Cell:
    A 64-byte (0x40) block within the grid. Addressed by (row, column).
    Contains wire flags, structural control bytes, and (for instruction-
    bearing rungs) stream-placement metadata.

Empty rung:
    All condition columns blank (""), AF blank. No wire flags set, no
    instruction stream. The simplest valid rung.

Wire topology:
    The arrangement of horizontal wires ("-"), vertical pass-throughs
    ("|"), and junction-down points ("T") across the condition grid.
    Encoded via three per-cell flag bytes: +0x19 (left), +0x1D (right),
    +0x21 (down). This is the structural skeleton that contacts and
    instructions are placed onto.

Condition:
    A contact or comparison instruction placed on a condition column.
    NOT supported in this version. Conditions set wire flags (like "-")
    and additionally write an instruction stream entry with a type
    marker, function code, and operand.

Instruction stream:
    Serialized instruction data in the payload region (0x0294+). Fields
    sit at stream-relative offsets from type markers (0x27XX). Operand
    strings are variable-length UTF-16LE, so each instruction shifts
    all downstream positions. NOT used in this version.

NOP:
    The simplest AF-column instruction. Encoded via a minimal byte
    model: col31 +0x1D = 1 (all rows), plus col0 +0x15 = 1 for
    non-first rows. Does not require an instruction stream entry.

Comment:
    Plain-text annotation on a rung. Stored as an RTF envelope (fixed
    prefix + cp1252 body + fixed suffix) in the payload region at
    0x0298, followed by a continuation stream (phase-A). Max 1400
    bytes. The comment does not live inside the cell grid — it occupies
    its own space in the payload region. For multi-row rungs, the
    comment adds an extra 0x1000 page to the buffer allocation.

Page:
    A 0x1000 (4096) byte allocation unit. A 1-row rung occupies 2
    pages (0x2000 = 8192 bytes). Additional rows add pages:
    page_count = ceil(rows / 2) + 1. A comment on a multi-row rung
    adds one more page for the terminal companion extent.

Header table:
    32 entries x 64 bytes starting at 0x0254. Entry N corresponds to
    column N. Contains the row-count word (+0x00/+0x01), column index
    (+0x0C), and family/context bytes (+0x05, +0x11, +0x17, +0x18)
    that are zero for wire-only rungs but become structural for
    instruction-bearing families.

Phase-A:
    A universal 0xFC8-byte continuation stream written immediately
    after the comment payload. Identical across all tested comment
    lengths. Provides structural scaffolding that Click expects after
    the RTF envelope. This is NOT cell grid data — it is stream data
    that happens to occupy addresses in the same range as the grid
    for short comments in small buffers.


Supported checklist
-------------------

Verified in Click (encode → paste → copy back → decode round-trip):

    [x] Empty rung, 1 row
    [x] Empty rung, 2..32 rows
    [x] Wire topology, 2..32 rows (-, |, T in any valid position)
    [x] Full horizontal wire, 1 row
    [x] NOP on row 0
    [x] NOP on non-first rows (with col0 +0x15 enable)
    [x] Plain comment, 1-row empty, short/medium/max1400 lengths
    [x] Plain comment, all lengths 1..1400 (including formerly broken
        mod-36 lengths like 100)
    [x] Plain comment + wire topology (1-row; payload and grid are separate)
    [x] Plain comment + NOP (1-row; payload and grid are separate)

    [ ] Plain comment on multi-row rung (requires extra page allocation
        for terminal companion extent; model understood but synthesis
        not built)
    [ ] Styled comments (bold/italic/underline RTF; crashes under
        current model)
    [ ] Contacts (NO, NC, edge, comparison, immediate variants)
    [ ] Coils / AF instructions (out, latch, reset)
    [ ] Instruction stream placement


Pipeline steps
--------------

    1. Allocate — page-aligned buffer from row count
    2. Header + cell structure — deterministic per-cell fields
    3. Comment — optional payload + phase-A (must precede wire flags)
    4. Wire flags — condition token grid (columns A..AE)
    5. AF column — NOP via minimal tested byte model

Steps 1-2 are handled by synthesize_empty_multirow. Steps 3-5 are
applied on top. Comment (step 3) is applied before wire flags because
phase-A overlaps the cell grid region for short comments — writing
wires after ensures they are not clobbered.

Future extension points for contacts and instructions are marked with
"FUTURE:" throughout. The main areas are:

    - Header seed bytes (+0x05, +0x11, +0x17, +0x18, trailer 0x0A59)
      become context-sensitive per instruction family.
    - Cell +0x39 linkage bytes are required for instruction-bearing rungs.
    - Condition columns gain contact/comparison tokens with instruction
      stream data (type markers 0x27XX, UTF-16LE operands).
    - AF column gains coil/output instructions (out, latch, reset) with
      operand streams beyond the current NOP-only model.
    - Instruction stream placement lives in the payload region and shifts
      with operand length; a stream builder replaces _apply_comment.
    - Multi-row comments require synthesizing the extra page and its
      terminal companion extent (font descriptors, CJK fallback tables).

This replaces:
    - All donor .bin file matching (5 wireframe families)
    - Short/medium/long comment families
    - Phase-B block programs
    - Wire flag clearing
    - The mod-36 length exclusion

Dependencies:
    - empty_multirow.synthesize_empty_multirow (steps 1-2)
    - topology constants (step 3-4)
    - One reference donor file for comment prefix/suffix/phase-A (step 5)

Integration checklist — items to retire when this module replaces codec_v2:

    Files to delete:
        - codec_v2.py (replaced entirely by this module)
        - nonempty_multirow.py (subsumed by steps 3-4 here)
        - resources/march8/grcecr_medium_native_20260308.bin
        - resources/march8/grcecr_max1400_native_20260308.bin
        - resources/march8/grcecr_fullwire_native_20260308.bin
        - resources/march8/grcecr_fullwire_nop_native_20260308.bin
        - resources/march8/grcecr_rows2_empty_native_20260308.bin
        - resources/march8/grcecr_rows2_vert_horiz_native_20260308.bin

    Files to keep:
        - resources/march8/grcecr_empty_native_20260308.bin (scaffold
          template for synthesize_empty_multirow)
        - resources/march8/grcecr_short_native_20260308.bin (comment
          donor for prefix/suffix/phase-A extraction)

    Dead code in codec_v2 replaced by generalized rules here:
        - _WIREFRAME_PAYLOADS / _match_wireframe_family
        - _load_comment_donors / _derive_shared_comment_wrapper
        - _derive_phase_a_stream / _derive_medium_phase_b_program
        - _apply_medium_phase_b / _clear_visible_wire_flags
        - _is_known_bad_medium_comment_length / _KNOWN_BAD_MEDIUM_LENGTH_MOD
        - MEDIUM_TYPE_A/B/C_OFFSETS / MEDIUM_PHASE_B_TRIAD_PERIOD
        - Short/medium/long comment family branching in
          _encode_plain_comment_payload

    Handoff sections that become historical after integration:
        - "Plain Comment Exact Offline Synthesis" (replaced by unified path)
        - "Phase 3 Wireframe Band Isolation" (replaced by programmatic
          construction)
        - Phase-B triad program documentation (no longer used)
        - The mod-36 / BLOCK_SIZE alignment discussion (bug no longer exists)

    Keep / adapt:
        - compile_rung_v2 / compile_rows_v2 (compile pipeline — wire the
          output to encode_rung instead of encode_compiled)
        - LadderRungV2 dataclass (or simplify to match encode_rung args)
        - decode path in March8V2Engine.decode (unchanged)
        - V2UnsupportedShapeError (still useful for validation)
        - Test fixtures that verify round-trip: decode(encode(rung)) == rung
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import resources

from .empty_multirow import synthesize_empty_multirow
from .topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    COLS_PER_ROW,
    cell_offset,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Single-rung clipboard buffer is 0x2000 (8192) bytes for 1-row rungs,
# scaling by 0x1000 pages for additional rows. The buffer is zero-padded.
# Multi-rung paste produces multiples of these (e.g. 12288 for split rungs
# is a known failure signature — means Click interpreted one rung as two).
#
# Validation method: encode → paste into Click → copy back → decode.
# A passing round-trip means verify-back length matches expected scaling
# and decoded topology/comment match the input.

PAYLOAD_LENGTH_OFFSET = 0x0294
PAYLOAD_BYTES_OFFSET = 0x0298
PHASE_A_LEN = 0xFC8
COMMENT_MAX_BYTES = 1400

# Comment-present flag written to header entry0 +0x17 and mirrored across
# all 63 phase-A periodic slots.  Native captures from the current Click
# version (v3.80) consistently produce 0x5A regardless of grid content
# (empty, sparse wires, full wires, NOP).  Two older captures showed 0x67
# and one legacy-prefix capture showed 0x65, but these appear to be
# version/session artefacts — the 0x5A value is dominant and round-trips
# cleanly.
COMMENT_FLAG = 0x5A

# NOTE: The native convention is len_dword = total payload bytes including
# the trailing NUL in the suffix. The prefix is a fixed RTF ANSI header,
# the body is plain text encoded as cp1252, and the suffix closes the RTF
# envelope. The body itself is NOT RTF-escaped — only the prefix/suffix are
# RTF structure. Styled comments (bold/italic/underline) would require RTF
# control words (\b, \i, \ul) within the body, but that path is currently
# unsupported (crashes under the current model).

CONDITION_COLUMNS = COLS_PER_ROW - 1  # A..AE (31 columns)
AF_COLUMN = COLS_PER_ROW - 1  # Column AF (index 31)

MIN_ROWS = 1
MAX_ROWS = 32

# Token → (horizontal_left, horizontal_right, vertical_down)
# NOTE: Horizontal asymmetry is proven — +0x1D (right) is the decisive
# flag for continuity. +0x19 (left) alone is insufficient and causes T
# to collapse to | (verified at rows 4/9/32). We write both for native
# parity, but if a minimal mode is ever needed, only +0x1D is required.
_TOKEN_FLAGS: dict[str, tuple[int, int, int]] = {
    "": (0, 0, 0),
    "-": (1, 1, 0),
    "|": (0, 0, 1),
    "T": (1, 1, 1),
}

SUPPORTED_CONDITION_TOKENS = frozenset(_TOKEN_FLAGS)

# FUTURE: Contact and comparison tokens will extend this map. Each contact
# type (NO, NC, edge, immediate variants) requires:
#   - Wire flags as above (typically "-" equivalent: left=1, right=1)
#   - An instruction stream entry with type marker (0x2711 NO, 0x2712 NC,
#     0x2713 edge) and function code
#   - UTF-16LE operand string (variable length — shifts downstream fields)
#   - Immediate contacts shift the function-code location by +2 bytes
# The token map will likely become a richer structure carrying both wire
# flags and stream-placement metadata.

# AF NOP encoding — minimal tested byte model:
#   row 0 NOP:     col31 +0x1D = 1
#   row N NOP:     col31 +0x1D = 1, col0 +0x15 = 1
#   native parity: row0 col0 +0x15 = 0 (already zero from empty base)
CELL_AF_NOP_OFFSET = 0x1D  # on col31: marks NOP output
CELL_NOP_ROW_ENABLE_OFFSET = 0x15  # on col0: required for non-first-row NOP

# FUTURE: AF instructions beyond NOP (out/latch/reset coils) will need:
#   - Type marker 0x2715 (out), 0x2716 (latch), 0x2717 (reset)
#   - Function codes (8193 out, 8195 latch, 8196 reset, plus immediate/range)
#   - Operand stream with UTF-16LE target address
#   - The AF cell byte model likely extends beyond +0x1D alone


# ---------------------------------------------------------------------------
# Comment framing — hardcoded from native capture (2026-03-09)
# ---------------------------------------------------------------------------

# RTF envelope prefix (105 bytes). Wraps plain-text comment body.
# Uses the full native form with \ansicpg1252 and \deflang1033 so that
# the payload length matches native captures and phase-A lands at the
# correct absolute positions in the buffer. Click normalizes both the
# short and long prefix forms on copy-back, but phase-A alignment is
# critical because it overlaps the cell grid region.
_PREFIX = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033"
    b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}\r\n"
    b"\\viewkind4\\uc1\\pard\\fs20 "
)

# RTF envelope suffix (11 bytes). Closes the RTF body.
_SUFFIX = b"\r\n\\par }\r\n\x00"

# Phase-A continuation stream (0xFC8 bytes). Loaded from a purpose-built
# resource file extracted from a native capture. This is structural
# scaffolding that Click expects immediately after the comment payload.
_PHASE_A = (
    resources.files("clicknick.ladder").joinpath("resources/comment_phase_a.bin").read_bytes()
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _set_wire_flags(
    out: bytearray,
    row_idx: int,
    col_idx: int,
    left: int,
    right: int,
    down: int,
) -> None:
    """Write the three wire-flag bytes for a single cell."""
    start = cell_offset(row_idx, col_idx)
    out[start + CELL_HORIZONTAL_LEFT_OFFSET] = left
    out[start + CELL_HORIZONTAL_RIGHT_OFFSET] = right
    out[start + CELL_VERTICAL_DOWN_OFFSET] = down


def _normalize_af(token: str) -> str:
    """Normalize an AF token to 'NOP' or ''.

    FUTURE: This will expand to handle coil instructions: out(Y001),
    latch(Y001), reset(Y001), and their immediate/range variants. Each
    will return a structured object rather than a string, carrying the
    instruction type, operand, and immediate flag.
    """
    stripped = token.strip().upper()
    if stripped == "NOP":
        return "NOP"
    if stripped == "":
        return ""
    raise ValueError(f"Unsupported AF token: {token!r}")


def _apply_comment(out: bytearray, text: str) -> None:
    """Write comment payload + phase-A into the payload region.

    The phase-A stream contains COMMENT_FLAG (0x5A) at a periodic stride
    of 0x40 bytes (starting at relative offset 0x13), mirroring the
    entry0 +0x17 header byte across all 63 cell-sized slots.  Tail bytes
    at +0x0FA1/+0x0FA5 are left at their resource-file baseline (0x00).
    """
    encoded = text.encode("cp1252")
    if len(encoded) > COMMENT_MAX_BYTES:
        raise ValueError(f"Comment exceeds {COMMENT_MAX_BYTES} bytes (got {len(encoded)})")
    payload = _PREFIX + encoded + _SUFFIX

    # Payload length (4 bytes LE at 0x0294)
    out[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET] = len(payload).to_bytes(4, "little")
    # Payload body (at 0x0298)
    payload_end = PAYLOAD_BYTES_OFFSET + len(payload)
    out[PAYLOAD_BYTES_OFFSET:payload_end] = payload

    # Phase-A immediately after payload, patched with COMMENT_FLAG
    phase_a = bytearray(_PHASE_A)
    for k in range(63):
        phase_a[0x13 + 0x40 * k] = COMMENT_FLAG

    out[payload_end : payload_end + len(phase_a)] = phase_a


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encode_rung(
    logical_rows: int,
    condition_rows: Sequence[Sequence[str]],
    af_tokens: Sequence[str],
    comment: str | None = None,
) -> bytes:
    """Encode a ladder rung to binary payload.

    Parameters
    ----------
    logical_rows:
        Number of rung rows (1..32).
    condition_rows:
        Row-major token grid. Each row has 31 condition-column tokens.
        Supported: ``""`` blank, ``"-"`` horizontal wire,
        ``"|"`` vertical pass-through, ``"T"`` junction-down.
    af_tokens:
        One per row. ``"NOP"`` encodes the NOP instruction on the AF
        column (col31 +0x1D, with col0 +0x15 enable for non-first rows);
        ``""`` leaves it blank.
    comment:
        Optional single-line comment text (cp1252, max 1400 bytes).
        Currently limited to 1-row rungs (multi-row needs extra page
        synthesis). Comment + wires and comment + NOP on 1-row rungs
        are supported (payload and cell grid occupy separate regions).

    Returns
    -------
    bytes
        Encoded binary payload ready for the target environment.
    """

    # --- Validate dimensions ---

    if not (MIN_ROWS <= logical_rows <= MAX_ROWS):
        raise ValueError(f"logical_rows must be {MIN_ROWS}..{MAX_ROWS}, got {logical_rows}")
    if len(condition_rows) != logical_rows:
        raise ValueError(f"Expected {logical_rows} condition rows, got {len(condition_rows)}")
    if len(af_tokens) != logical_rows:
        raise ValueError(f"Expected {logical_rows} AF tokens, got {len(af_tokens)}")
    for row_idx, row in enumerate(condition_rows):
        if len(row) != CONDITION_COLUMNS:
            raise ValueError(f"Row {row_idx}: expected {CONDITION_COLUMNS} columns, got {len(row)}")
        for col_idx, token in enumerate(row):
            if token not in SUPPORTED_CONDITION_TOKENS:
                raise ValueError(f"Unsupported token {token!r} at row={row_idx}, col={col_idx}")
            if col_idx == 0 and token in ("|", "T"):
                raise ValueError(
                    f"Vertical-down tokens are not allowed in column A "
                    f"(row={row_idx}, token={token!r})"
                )

    # --- Validate comment constraints ---
    # Comments occupy the payload region (0x0294+), separate from the cell
    # grid (0x0A60+). They do NOT conflict with wire flags. The 1-row limit
    # exists because multi-row comments add an extra 0x1000 page to the
    # buffer for a terminal companion extent (font descriptors, CJK fallback
    # tables), and synthesis of that extra page is not yet built.
    # Comment + wires and comment + NOP on a 1-row rung are structurally
    # sound — comment payload (0x0294+) and cell grid (0x0A60+) don't overlap.

    has_comment = comment is not None and comment != ""
    if has_comment:
        if logical_rows != 1:
            raise ValueError(
                "Comments on multi-row rungs require terminal companion "
                "page synthesis (not yet implemented)"
            )

    # --- Step 1–2: Allocate + header + cell structure ---
    # FUTURE: Instruction-bearing rungs require a header seed that sets
    # context-sensitive bytes on all 32 header entries:
    #   - +0x05: structural gate (e.g. 0x04 for second-immediate families)
    #   - +0x11: family classifier (e.g. 0x0B for second-immediate)
    #   - +0x17/+0x18: capture-family classifiers (observed: 0x15/0x01,
    #     0x0D/0x01, 0xEA/0x00 — decision table incomplete)
    #   - Trailer byte 0x0A59 mirrors +0x05
    # These are all zero for wire-only/comment rungs and validated as safe
    # at that value. When instruction encoding is added, encode_rung will
    # need a header_seed parameter or equivalent.
    #
    # FUTURE: Instruction-bearing rungs also require cell +0x39 = 1 on
    # row0/row1 cells (all columns) as a rung-assembly linkage flag.
    # Without it, Click splits one intended rung into multiple records.
    # Zero is correct for wire-only rungs.

    out = bytearray(synthesize_empty_multirow(logical_rows))

    # --- Step 3: Comment ---
    # Comment MUST be applied before wire flags because phase-A (0xFC8
    # bytes after the RTF payload) overlaps the cell grid region for
    # short comments in 1-row buffers. Writing wires after phase-A
    # ensures wire flag bytes are not clobbered.
    #
    # FUTURE: Two known limitations to address:
    #   1. Multi-row comments: the buffer needs an extra 0x1000 page for
    #      a terminal companion extent carrying renderer/layout metadata
    #      (font descriptors, CJK fallback tables). The page-extent model
    #      is understood (handoff: row32 max1400 = 73728 = 18 pages vs
    #      69632 = 17 pages without comment) but synthesis not yet built.
    #   2. Styled comments (RTF bold/italic/underline): the payload is
    #      standard RTF (\b, \i, \ul tokens) but styled probes crash
    #      under the current model. Likely requires companion bytes in
    #      the continuation stream that plain comments don't need.

    # Compute phase-A start once (used by steps 3-5 for comment rungs).
    phase_a_start: int | None = None
    if has_comment:
        # Header entry0 +0x17: unified comment flag (0x5A).
        # Native captures from current Click version show 0x5A regardless
        # of grid content (empty, sparse wires, full wires, NOP).
        out[0x0254 + 0x17] = COMMENT_FLAG

        # Trailer byte 0x0A59 = 0x01 for all comment rungs (confirmed
        # across sparse, full-wire, and NOP-only native captures).
        out[0x0A59] = 0x01

        _apply_comment(out, comment)

        encoded = comment.encode("cp1252")
        payload_len = len(_PREFIX) + len(encoded) + len(_SUFFIX)
        phase_a_start = PAYLOAD_BYTES_OFFSET + payload_len

        # Zero out everything after phase-A ends.
        phase_a_end = phase_a_start + PHASE_A_LEN
        out[phase_a_end:] = b"\x00" * (len(out) - phase_a_end)

    # --- Step 4: Wire flags on condition columns (A..AE) ---
    # For comment rungs, wire data lives in the phase-A stride, NOT in the
    # cell grid.  Native captures confirm cell grid +0x19/+0x1D are all zero
    # for comment rungs.  Instead, wires are at phase-A-relative positions:
    #   slot = col_idx + 31   (within the phase-A 0x40-byte stride)
    #   left  wire: slot_base + 0x21
    #   right wire: slot_base + 0x25
    # The phase-A stream starts immediately after the RTF payload, so wire
    # positions shift with comment length.  This is payload-length-dependent
    # but Click reads the payload length field and computes accordingly.
    #
    # For non-comment rungs, wires use the cell grid model as before.

    if has_comment:
        assert phase_a_start is not None
        for col_idx, token in enumerate(condition_rows[0]):
            left, right, _down = _TOKEN_FLAGS[token]
            slot_base = phase_a_start + (col_idx + 31) * 0x40
            if left:
                out[slot_base + 0x21] = 1
            if right:
                out[slot_base + 0x25] = 1
    else:
        for row_idx, row in enumerate(condition_rows):
            for col_idx, token in enumerate(row):
                left, right, down = _TOKEN_FLAGS[token]
                _set_wire_flags(out, row_idx, col_idx, left, right, down)

    # --- Step 5: AF column (NOP encoding) ---
    # For comment rungs, NOP uses phase-A slot 62 + 0x25 (confirmed by
    # native nop-only capture).  For non-comment rungs, cell grid model.

    if has_comment:
        assert phase_a_start is not None
        for af in af_tokens:
            if _normalize_af(af) == "NOP":
                slot_base = phase_a_start + (AF_COLUMN + 31) * 0x40
                out[slot_base + 0x25] = 1
    else:
        for row_idx, af in enumerate(af_tokens):
            if _normalize_af(af) == "NOP":
                nop_start = cell_offset(row_idx, AF_COLUMN)
                out[nop_start + CELL_AF_NOP_OFFSET] = 1

                if row_idx > 0:
                    col0_start = cell_offset(row_idx, 0)
                    out[col0_start + CELL_NOP_ROW_ENABLE_OFFSET] = 1

    return bytes(out)
