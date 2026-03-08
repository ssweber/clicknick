#!/usr/bin/env python3
"""Synthesize the exact March 8 plain payload plus universal phase-A continuation stream."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EMPTY_CAPTURE = "grcecr_empty_native_20260308.bin"
SHORT_CAPTURE = "grcecr_short_native_20260308.bin"

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

PHASE_A_LEN = 0xFC8
PAYLOAD_LENGTH_OFFSET = 0x0294
PAYLOAD_BYTES_OFFSET = 0x0298


def _payload_end(data: bytes) -> int:
    return PAYLOAD_BYTES_OFFSET + int.from_bytes(data[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET], "little")


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
    suffix_len = min(len(payload) - (payload.find(body) + len(body)) for payload, body in zip(payloads, bodies))
    prefix = payloads[0][:prefix_len]
    suffix = payloads[0][-suffix_len:]

    for payload, body in zip(payloads, bodies):
        if payload != prefix + body + suffix:
            raise ValueError("Plain payload wrapper was not exact for all March 8 captures")

    return prefix, suffix


def _derive_phase_a_stream(capture_dir: Path) -> bytes:
    captures = [(capture_dir / spec["capture"]).read_bytes() for spec in COMMENT_CASES.values()]
    suffixes = [data[_payload_end(data) : _payload_end(data) + PHASE_A_LEN] for data in captures]
    if len({chunk for chunk in suffixes}) != 1:
        raise ValueError("Universal phase-A stream is not exact across the March 8 plain-comment captures")
    return suffixes[0]


def _synthesize_case(
    *,
    body_text: str,
    base: bytes,
    payload_prefix: bytes,
    payload_suffix: bytes,
    phase_a_stream: bytes,
) -> bytes:
    payload = payload_prefix + body_text.encode("cp1252") + payload_suffix
    out = bytearray(base)
    out[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET] = len(payload).to_bytes(4, "little")
    end = PAYLOAD_BYTES_OFFSET + len(payload)
    out[PAYLOAD_BYTES_OFFSET:end] = payload
    out[end : end + len(phase_a_stream)] = phase_a_stream
    return bytes(out)


def _diff_counts(left: bytes, right: bytes) -> dict[str, int]:
    return {
        "post_payload_diffs": sum(left[i] != right[i] for i in range(0x08FD, 0x0A60)),
        "row0_diffs": sum(left[i] != right[i] for i in range(0x0A60, 0x1260)),
        "row1_diffs": sum(left[i] != right[i] for i in range(0x1260, 0x1A60)),
        "tail_diffs": sum(left[i] != right[i] for i in range(0x1A60, 0x2000)),
        "full_diffs": sum(left[i] != right[i] for i in range(len(left))),
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

    base = (args.capture_dir / EMPTY_CAPTURE).read_bytes()
    payload_prefix, payload_suffix = _derive_plain_payload_wrapper(args.capture_dir)
    phase_a_stream = _derive_phase_a_stream(args.capture_dir)

    results = []
    for case_name, spec in COMMENT_CASES.items():
        body_text = Path(spec["body_file"]).read_text().rstrip("\r\n")
        target = (args.capture_dir / spec["capture"]).read_bytes()
        synthesized = _synthesize_case(
            body_text=body_text,
            base=base,
            payload_prefix=payload_prefix,
            payload_suffix=payload_suffix,
            phase_a_stream=phase_a_stream,
        )

        output_file = None
        if args.output_dir is not None:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            output_file = args.output_dir / f"{case_name}_phase_a.bin"
            output_file.write_bytes(synthesized)

        results.append(
            {
                "case": case_name,
                "output_file": str(output_file) if output_file is not None else None,
                "diffs_vs_target": _diff_counts(synthesized, target),
            }
        )

    payload_info = {
        "payload_prefix_len": len(payload_prefix),
        "payload_suffix_len": len(payload_suffix),
        "phase_a_len": len(phase_a_stream),
    }
    if args.json:
        print(json.dumps({"payload_info": payload_info, "results": results}, indent=2))
    else:
        print(f"payload_prefix_len={payload_info['payload_prefix_len']}")
        print(f"payload_suffix_len={payload_info['payload_suffix_len']}")
        print(f"phase_a_len={payload_info['phase_a_len']}")
        print()
        for result in results:
            print(f"case={result['case']}")
            for name, value in result["diffs_vs_target"].items():
                print(f"{name}={value}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
