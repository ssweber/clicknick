#!/usr/bin/env python3
"""Profile March 8 plain-comment synthesis readiness from the clean empty baseline."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

PAYLOAD_LENGTH_OFFSET = 0x0294
PAYLOAD_BYTES_OFFSET = 0x0298

REGIONS = {
    "prefix_band": (0x0000, 0x0254),
    "metadata_pre_payload": (0x0254, 0x0294),
    "payload_window": (0x0294, 0x08FD),
    "metadata_post_payload_window": (0x08FD, 0x0A54),
    "gap_band": (0x0A54, 0x0A60),
    "row0_band": (0x0A60, 0x1260),
    "row1_band": (0x1260, 0x1A60),
    "tail_band": (0x1A60, 0x2000),
}

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

EMPTY_CAPTURE = "grcecr_empty_native_20260308.bin"
FULLWIRE_CAPTURE = "grcecr_fullwire_native_20260308.bin"


@dataclass(frozen=True)
class PayloadParts:
    prefix: bytes
    suffix: bytes


def _extract_payload(payload: bytes) -> bytes:
    length = int.from_bytes(payload[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET], "little")
    return payload[PAYLOAD_BYTES_OFFSET : PAYLOAD_BYTES_OFFSET + length]


def _load_capture(capture_dir: Path, filename: str) -> bytes:
    return (capture_dir / filename).read_bytes()


def _diff_count(left: bytes, right: bytes, start: int, stop: int) -> int:
    return sum(left[i] != right[i] for i in range(start, stop))


def _diff_offsets(left: bytes, right: bytes, start: int, stop: int) -> set[int]:
    return {i - start for i in range(start, stop) if left[i] != right[i]}


def _derive_plain_payload_parts(capture_dir: Path) -> PayloadParts:
    payloads = []
    body_bytes = []
    for case in COMMENT_CASES.values():
        capture = _load_capture(capture_dir, case["capture"])
        payloads.append(_extract_payload(capture))
        body_text = Path(case["body_file"]).read_text().rstrip("\r\n")
        body_bytes.append(body_text.encode("cp1252"))

    prefix_len = 0
    while all(
        prefix_len < len(payload)
        and prefix_len < len(body)
        and payload[prefix_len] == payloads[0][prefix_len]
        for payload, body in zip(payloads, body_bytes)
    ):
        prefix_len += 1

    # The common prefix ends just before the body text starts.
    prefix_len = min(
        idx
        for idx in (
            payload.find(body)
            for payload, body in zip(payloads, body_bytes)
        )
        if idx >= 0
    )

    suffix_len = min(
        len(payload) - (payload.find(body) + len(body))
        for payload, body in zip(payloads, body_bytes)
    )
    prefix = payloads[0][:prefix_len]
    suffix = payloads[0][-suffix_len:]

    for payload, body in zip(payloads, body_bytes):
        expected = prefix + body + suffix
        if payload != expected:
            raise ValueError("Plain payload envelope derivation was not exact for all March 8 captures")

    return PayloadParts(prefix=prefix, suffix=suffix)


def _build_plain_payload(body_text: str, payload_parts: PayloadParts) -> bytes:
    return payload_parts.prefix + body_text.encode("cp1252") + payload_parts.suffix


def _profile_case(
    *,
    name: str,
    capture: bytes,
    empty_capture: bytes,
    fullwire_capture: bytes,
    body_text: str,
    payload_parts: PayloadParts,
) -> dict[str, object]:
    region_counts = {
        region: _diff_count(empty_capture, capture, start, stop)
        for region, (start, stop) in REGIONS.items()
    }

    row1_comment = _diff_offsets(empty_capture, capture, *REGIONS["row1_band"])
    tail_comment = _diff_offsets(empty_capture, capture, *REGIONS["tail_band"])
    row1_fullwire = _diff_offsets(empty_capture, fullwire_capture, *REGIONS["row1_band"])
    tail_fullwire = _diff_offsets(empty_capture, fullwire_capture, *REGIONS["tail_band"])

    payload = _extract_payload(capture)
    synthesized_payload = _build_plain_payload(body_text, payload_parts)
    if payload != synthesized_payload:
        raise ValueError(f"Payload-window synthesis was not exact for case {name!r}")

    reusable_counts = {
        "row1_band_from_fullwire": region_counts["row1_band"] if row1_comment == row1_fullwire else 0,
        "tail_band_from_fullwire": region_counts["tail_band"] if tail_comment == tail_fullwire else 0,
    }

    unresolved_companion_count = (
        region_counts["metadata_post_payload_window"]
        + region_counts["gap_band"]
        + region_counts["row0_band"]
        + region_counts["row1_band"]
        + region_counts["tail_band"]
        - reusable_counts["row1_band_from_fullwire"]
        - reusable_counts["tail_band_from_fullwire"]
    )

    return {
        "case": name,
        "payload_length_dword": int.from_bytes(capture[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET], "little"),
        "plain_payload_text_length": len(body_text),
        "payload_window_exact_from_plain_text": True,
        "region_counts_vs_empty_1row": region_counts,
        "fullwire_reuse_candidates": {
            "row1_band_exact": row1_comment == row1_fullwire,
            "tail_band_exact": tail_comment == tail_fullwire,
            "row1_band_overlap_count": len(row1_comment & row1_fullwire),
            "tail_band_overlap_count": len(tail_comment & tail_fullwire),
        },
        "unresolved_companion_count_after_plain_payload_and_exact_fullwire_reuse": unresolved_companion_count,
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
        "--json",
        action="store_true",
        help="Emit JSON instead of plain text",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    empty_capture = _load_capture(args.capture_dir, EMPTY_CAPTURE)
    fullwire_capture = _load_capture(args.capture_dir, FULLWIRE_CAPTURE)
    payload_parts = _derive_plain_payload_parts(args.capture_dir)

    results = {
        "plain_payload_envelope": {
            "prefix_len": len(payload_parts.prefix),
            "suffix_len": len(payload_parts.suffix),
            "prefix_preview_latin1": payload_parts.prefix.decode("latin1"),
            "suffix_preview_latin1": payload_parts.suffix.decode("latin1"),
        },
        "cases": [],
    }

    for name, spec in COMMENT_CASES.items():
        capture = _load_capture(args.capture_dir, spec["capture"])
        body_text = Path(spec["body_file"]).read_text().rstrip("\r\n")
        results["cases"].append(
            _profile_case(
                name=name,
                capture=capture,
                empty_capture=empty_capture,
                fullwire_capture=fullwire_capture,
                body_text=body_text,
                payload_parts=payload_parts,
            )
        )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"plain_payload_prefix_len={results['plain_payload_envelope']['prefix_len']}")
        print(f"plain_payload_suffix_len={results['plain_payload_envelope']['suffix_len']}")
        print()
        for case in results["cases"]:
            print(f"case={case['case']}")
            print(f"payload_length_dword={case['payload_length_dword']}")
            print(f"plain_payload_text_length={case['plain_payload_text_length']}")
            print(
                "unresolved_companion_count_after_plain_payload_and_exact_fullwire_reuse="
                f"{case['unresolved_companion_count_after_plain_payload_and_exact_fullwire_reuse']}"
            )
            print(
                "fullwire_row1_exact="
                f"{case['fullwire_reuse_candidates']['row1_band_exact']}"
            )
            print(
                "fullwire_tail_exact="
                f"{case['fullwire_reuse_candidates']['tail_band_exact']}"
            )
            for region, count in case["region_counts_vs_empty_1row"].items():
                print(f"{region}={count}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
