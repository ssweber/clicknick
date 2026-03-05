import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from devtools.noise_apply import apply_copy_from_donor, apply_set_constant, resolve_offsets


def test_copy_from_donor_only_mutates_selected_offsets_and_is_idempotent() -> None:
    input_bytes = bytes([0] * 8192)
    donor = bytearray(input_bytes)
    donor[10] = 0xAA
    donor[20] = 0xBB
    donor[30] = 0xCC

    mask = {
        "global": {"volatile_offsets": [10, 20]},
        "classification": {"session_tuple_candidates": [10, 20]},
    }
    offsets = resolve_offsets(mask=mask, classes=["session_tuple_candidates"])
    patched, changed = apply_copy_from_donor(input_bytes, bytes(donor), offsets)

    assert changed == 2
    assert patched[10] == 0xAA
    assert patched[20] == 0xBB
    assert patched[30] == 0x00

    patched_again, changed_again = apply_copy_from_donor(patched, bytes(donor), offsets)
    assert patched_again == patched
    assert changed_again == 0


def test_set_constant_mode_uses_resolved_offsets_only() -> None:
    input_data = bytearray([0] * 8192)
    input_data[10] = 0x11
    input_data[20] = 0x22
    input_data[30] = 0x33

    mask = {"global": {"volatile_offsets": [10, 20]}}
    offsets = resolve_offsets(mask=mask)
    patched, changed = apply_set_constant(bytes(input_data), offsets, 0x7F)

    assert changed == 2
    assert patched[10] == 0x7F
    assert patched[20] == 0x7F
    assert patched[30] == 0x33
