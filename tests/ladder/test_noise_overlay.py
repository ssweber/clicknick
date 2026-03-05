import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from devtools.noise_overlay import BUFFER_SIZE, CaptureRecord, build_overlay, session_tuple_offsets


def _record(name: str, data: bytes) -> CaptureRecord:
    return CaptureRecord(
        name=name,
        source_kind="file",
        source_field="file",
        source_path=Path(f"{name}.bin"),
        scenario="test",
        expected_rows=("R,...,:,...",),
        group="test",
        record_len=BUFFER_SIZE,
        data=data,
        topology_hash="topology-hash",
    )


def test_session_tuple_offsets_are_classified_as_candidates_when_they_vary() -> None:
    baseline = bytearray(BUFFER_SIZE)
    shifted = bytearray(BUFFER_SIZE)
    for offset in session_tuple_offsets():
        shifted[offset] = 0x5A

    overlay = build_overlay(
        [
            _record("baseline", bytes(baseline)),
            _record("shifted", bytes(shifted)),
        ]
    )

    volatile = set(overlay["global"]["volatile_offsets"])
    expected = set(session_tuple_offsets())
    assert volatile == expected
    assert set(overlay["classification"]["session_tuple_candidates"]) == expected
