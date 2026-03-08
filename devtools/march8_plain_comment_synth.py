#!/usr/bin/env python3
"""Synthesize the clean March 8 plain-comment natives exactly with offline helpers only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PAYLOAD_LENGTH_OFFSET = 0x0294
PAYLOAD_BYTES_OFFSET = 0x0298
PHASE_A_LEN = 0xFC8
MEDIUM_PHASE_B_TRIAD_PERIOD = 9
BLOCK_SIZE = 0x40

EMPTY_CAPTURE = "grcecr_empty_native_20260308.bin"
FULLWIRE_CAPTURE = "grcecr_fullwire_native_20260308.bin"

COMMENT_CASES = {
    "short": {
        "capture": "grcecr_short_native_20260308.bin",
        "body_file": "scratchpad/rungcomment_short_body_20260308.txt",
    },
    "medium": {
        "capture": "grcecr_medium_native_20260308.bin",
        "body_file": "scratchpad/rungcomment_medium_body_20260308.txt",
    },
    "max1400": {
        "capture": "grcecr_max1400_native_20260308.bin",
        "body_file": "scratchpad/max1400_comment_body_20260307.txt",
    },
}

MEDIUM_TYPE_A_OFFSETS = {
    0x00: 0x10,
    0x02: 0x03,
    0x0C: 0x01,
    0x18: 0x10,
    0x1A: 0x03,
    0x24: 0x01,
    0x30: 0x10,
    0x32: 0x03,
    0x3C: 0x01,
}

MEDIUM_TYPE_B_OFFSETS = {
    0x08: 0x10,
    0x0A: 0x03,
    0x14: 0x01,
    0x20: 0x10,
    0x22: 0x03,
    0x2C: 0x01,
    0x38: 0x10,
    0x3A: 0x03,
}

MEDIUM_TYPE_C_OFFSETS = {
    0x04: 0x01,
    0x10: 0x10,
    0x12: 0x03,
    0x1C: 0x01,
    0x28: 0x10,
    0x2A: 0x03,
    0x34: 0x01,
}


def _payload_end(data: bytes) -> int:
    return PAYLOAD_BYTES_OFFSET + int.from_bytes(
        data[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET],
        "little",
    )


def _extract_payload(data: bytes) -> bytes:
    end = _payload_end(data)
    return data[PAYLOAD_BYTES_OFFSET:end]


def _derive_plain_payload_wrapper(capture_dir: Path) -> tuple[bytes, bytes]:
    captures = [(capture_dir / spec["capture"]).read_bytes() for spec in COMMENT_CASES.values()]
    bodies = [
        Path(spec["body_file"]).read_text().rstrip("\r\n").encode("cp1252")
        for spec in COMMENT_CASES.values()
    ]
    payloads = [_extract_payload(data) for data in captures]

    prefix_len = min(payload.find(body) for payload, body in zip(payloads, bodies))
    suffix_len = min(
        len(payload) - (payload.find(body) + len(body))
        for payload, body in zip(payloads, bodies)
    )
    prefix = payloads[0][:prefix_len]
    suffix = payloads[0][-suffix_len:]

    for payload, body in zip(payloads, bodies):
        if payload != prefix + body + suffix:
            raise ValueError("Plain payload wrapper was not exact for all March 8 captures")

    return prefix, suffix


def _derive_phase_a_stream(capture_dir: Path) -> bytes:
    captures = [(capture_dir / spec["capture"]).read_bytes() for spec in COMMENT_CASES.values()]
    chunks = [data[_payload_end(data) : _payload_end(data) + PHASE_A_LEN] for data in captures]
    if len(set(chunks)) != 1:
        raise ValueError("Phase A was not exact across the March 8 plain-comment captures")
    return chunks[0]


def _derive_medium_phase_b_program(capture_dir: Path) -> dict[str, object]:
    medium = (capture_dir / COMMENT_CASES["medium"]["capture"]).read_bytes()
    start = _payload_end(medium) + PHASE_A_LEN
    full_block_count = (0x2000 - start) // BLOCK_SIZE
    tail_len = (0x2000 - start) % BLOCK_SIZE
    full_blocks = [
        medium[start + idx * BLOCK_SIZE : start + (idx + 1) * BLOCK_SIZE]
        for idx in range(full_block_count)
    ]
    triad_period = MEDIUM_PHASE_B_TRIAD_PERIOD
    period = triad_period * 3

    for idx in range(full_block_count - period):
        if full_blocks[idx] != full_blocks[idx + period]:
            raise ValueError(f"Medium phase-B period {period} failed at block {idx}")

    tail = medium[start + full_block_count * BLOCK_SIZE : 0x2000]
    expected_tail = full_blocks[full_block_count % period][:tail_len]
    if tail != expected_tail:
        raise ValueError("Medium phase-B tail was not the truncated next block in the repeating program")

    triads = []
    for triad_idx in range(triad_period):
        a = full_blocks[triad_idx * 3 + 0]
        b = full_blocks[triad_idx * 3 + 1]
        c = full_blocks[triad_idx * 3 + 2]
        triads.append(
            {
                "a1": a[0x14],
                "a2": a[0x2C],
                "b1": b[0x04],
                "b2": b[0x1C],
                "b3": b[0x34],
                "c1": c[0x0C],
                "c2": c[0x24],
                "c3": c[0x3C],
            }
        )

    ring_r1 = [triad["a1"] for triad in triads]
    ring_r2 = [triad["a2"] for triad in triads]
    ring_r3 = [triad["b1"] for triad in triads]
    ring_r4 = [triad["b2"] for triad in triads]

    for idx, triad in enumerate(triads):
        shifted = (idx + 5) % triad_period
        if triad["b3"] != ring_r1[shifted]:
            raise ValueError("Medium ring relation b3 -> r1 failed")
        if triad["c1"] != ring_r2[shifted]:
            raise ValueError("Medium ring relation c1 -> r2 failed")
        if triad["c2"] != ring_r3[shifted]:
            raise ValueError("Medium ring relation c2 -> r3 failed")
        if triad["c3"] != ring_r4[shifted]:
            raise ValueError("Medium ring relation c3 -> r4 failed")

    return {
        "triad_period": triad_period,
        "ring_r1": ring_r1,
        "ring_r2": ring_r2,
        "ring_r3": ring_r3,
        "ring_r4": ring_r4,
        "tail_len": tail_len,
    }


def _build_plain_payload(body_text: str, prefix: bytes, suffix: bytes) -> bytes:
    return prefix + body_text.encode("cp1252") + suffix


def _apply_payload_and_phase_a(base: bytes, payload: bytes, phase_a_stream: bytes) -> bytearray:
    out = bytearray(base)
    out[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET] = len(payload).to_bytes(4, "little")
    payload_end = PAYLOAD_BYTES_OFFSET + len(payload)
    out[PAYLOAD_BYTES_OFFSET:payload_end] = payload
    out[payload_end : payload_end + len(phase_a_stream)] = phase_a_stream
    return out


def _apply_medium_phase_b(out: bytearray, start: int, program: dict[str, object]) -> None:
    triad_period = program["triad_period"]
    ring_r1 = program["ring_r1"]
    ring_r2 = program["ring_r2"]
    ring_r3 = program["ring_r3"]
    ring_r4 = program["ring_r4"]
    tail_len = program["tail_len"]

    full_block_count = (0x2000 - start) // BLOCK_SIZE
    for idx in range(full_block_count):
        triad_idx = (idx // 3) % triad_period
        block_type = idx % 3
        shifted = (triad_idx + 5) % triad_period
        block = bytearray(BLOCK_SIZE)
        if block_type == 0:
            for off, value in MEDIUM_TYPE_A_OFFSETS.items():
                block[off] = value
            block[0x14] = ring_r1[triad_idx]
            block[0x2C] = ring_r2[triad_idx]
        elif block_type == 1:
            for off, value in MEDIUM_TYPE_B_OFFSETS.items():
                block[off] = value
            block[0x04] = ring_r3[triad_idx]
            block[0x1C] = ring_r4[triad_idx]
            block[0x34] = ring_r1[shifted]
        else:
            for off, value in MEDIUM_TYPE_C_OFFSETS.items():
                block[off] = value
            block[0x0C] = ring_r2[shifted]
            block[0x24] = ring_r3[shifted]
            block[0x3C] = ring_r4[shifted]
        off = start + idx * BLOCK_SIZE
        out[off : off + BLOCK_SIZE] = block

    if tail_len:
        tail_off = start + full_block_count * BLOCK_SIZE
        triad_idx = (full_block_count // 3) % triad_period
        block = bytearray(BLOCK_SIZE)
        for off, value in MEDIUM_TYPE_A_OFFSETS.items():
            block[off] = value
        block[0x14] = ring_r1[triad_idx]
        block[0x2C] = ring_r2[triad_idx]
        out[tail_off:0x2000] = block[:tail_len]


def _synthesize_case(
    *,
    name: str,
    body_text: str,
    empty_capture: bytes,
    fullwire_capture: bytes,
    payload_prefix: bytes,
    payload_suffix: bytes,
    phase_a_stream: bytes,
    medium_phase_b_program: dict[str, object],
) -> bytes:
    payload = _build_plain_payload(body_text, payload_prefix, payload_suffix)
    out = _apply_payload_and_phase_a(empty_capture, payload, phase_a_stream)
    phase_b_start = PAYLOAD_BYTES_OFFSET + len(payload) + len(phase_a_stream)

    if name == "medium":
        _apply_medium_phase_b(out, phase_b_start, medium_phase_b_program)
    elif name == "max1400":
        out[0x1260:0x2000] = fullwire_capture[0x1260:0x2000]
    elif name != "short":
        raise ValueError(f"Unsupported case {name!r}")

    return bytes(out)


def _diff_counts(left: bytes, right: bytes) -> dict[str, int]:
    return {
        "post_payload_diffs": sum(left[i] != right[i] for i in range(0x08FD, 0x0A60)),
        "row0_diffs": sum(left[i] != right[i] for i in range(0x0A60, 0x1260)),
        "row1_diffs": sum(left[i] != right[i] for i in range(0x1260, 0x1A60)),
        "tail_diffs": sum(left[i] != right[i] for i in range(0x1A60, 0x2000)),
        "full_diffs": sum(a != b for a, b in zip(left, right)),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=Path("scratchpad/captures"),
        help="Directory containing March 8 canonical captures",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory to write synthesized outputs",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of plain text",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    empty_capture = (args.capture_dir / EMPTY_CAPTURE).read_bytes()
    fullwire_capture = (args.capture_dir / FULLWIRE_CAPTURE).read_bytes()
    payload_prefix, payload_suffix = _derive_plain_payload_wrapper(args.capture_dir)
    phase_a_stream = _derive_phase_a_stream(args.capture_dir)
    medium_phase_b_program = _derive_medium_phase_b_program(args.capture_dir)

    results = []
    for name, spec in COMMENT_CASES.items():
        body_text = Path(spec["body_file"]).read_text().rstrip("\r\n")
        target = (args.capture_dir / spec["capture"]).read_bytes()
        synthesized = _synthesize_case(
            name=name,
            body_text=body_text,
            empty_capture=empty_capture,
            fullwire_capture=fullwire_capture,
            payload_prefix=payload_prefix,
            payload_suffix=payload_suffix,
            phase_a_stream=phase_a_stream,
            medium_phase_b_program=medium_phase_b_program,
        )

        output_file = None
        if args.output_dir is not None:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            output_file = args.output_dir / f"{name}_plain_comment_exact.bin"
            output_file.write_bytes(synthesized)

        results.append(
            {
                "case": name,
                "payload_end": _payload_end(target),
                "phase_b_start": _payload_end(target) + PHASE_A_LEN,
                "output_file": str(output_file) if output_file is not None else None,
                "diffs_vs_target": _diff_counts(synthesized, target),
            }
        )

    result = {
        "payload_prefix_len": len(payload_prefix),
        "payload_suffix_len": len(payload_suffix),
        "phase_a_len": len(phase_a_stream),
        "medium_phase_b_triad_period": medium_phase_b_program["triad_period"],
        "medium_phase_b_tail_len": medium_phase_b_program["tail_len"],
        "results": results,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"payload_prefix_len={result['payload_prefix_len']}")
        print(f"payload_suffix_len={result['payload_suffix_len']}")
        print(f"phase_a_len={result['phase_a_len']}")
        print(f"medium_phase_b_triad_period={result['medium_phase_b_triad_period']}")
        print(f"medium_phase_b_tail_len={result['medium_phase_b_tail_len']}")
        print()
        for row in results:
            print(f"case={row['case']}")
            print(f"phase_b_start={hex(row['phase_b_start'])}")
            for name, value in row["diffs_vs_target"].items():
                print(f"{name}={value}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
