"""Shared ladder capture workflow engine for CLI and TUI frontends."""

from __future__ import annotations

import csv
import glob
import io
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyclickplc.addresses import format_address_display, get_addr_key, parse_address

from ..csv.shorthand import format_comment_shorthand_row, normalize_shorthand_row
from ..utils.mdb_operations import ensure_addresses_exist
from ..utils.mdb_shared import find_click_database
from . import capture_registry
from .clipboard import copy_to_clipboard, find_click_hwnd, read_from_clipboard
from .codec import ClickCodec, HeaderSeed
from .topology import HEADER_ENTRY_BASE, cell_offset, header_structural_equal, parse_wire_topology

FIXTURE_MANIFEST_VERSION = 2
FIXTURE_MANIFEST_DESCRIPTION = (
    "Hermetic ladder capture fixtures curated from vetted scratchpad captures."
)
PROFILE_REPORT_BUFFER_SIZE = 8192
PROFILE_REPORT_TRAILER_OFFSET = 0x0A59
PROFILE_REPORT_CELL_ROW = 0
PROFILE_REPORT_CELL_COLUMN = 4
PROFILE_COLUMNS_DEFAULT_ROWS = (0, 1)
PROFILE_COLUMNS_DEFAULT_COLS = tuple(range(32))
PROFILE_COLUMNS_DEFAULT_OFFSETS = (0x05, 0x11, 0x1A, 0x1B)
PROFILE_REPORT_HEADER_FIELDS = (
    "capture_label",
    "capture_type",
    "scenario",
    "payload_file",
    "record_len",
    "cell_05",
    "cell_11",
    "cell_1a",
    "cell_1b",
    "header_05",
    "header_11",
    "header_17",
    "header_18",
    "trailer_0a59",
)
PROFILE_COLUMNS_REPORT_BASE_FIELDS = (
    "capture_label",
    "capture_type",
    "scenario",
    "payload_file",
    "record_len",
    "row",
    "column",
)
SEED_SOURCES = {"clipboard", "scaffold", "entry", "file"}
ADDRESS_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])")
ADDRESS_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})\s*\.\.\s*([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])"
)
AUTO_LABEL_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_]+")

VerifyStatus = str


@dataclass(frozen=True)
class CaptureWorkflowPaths:
    root: Path
    scratchpad_manifest_path: Path
    fixture_manifest_path: Path
    captures_dir: Path
    fixtures_dir: Path

    @classmethod
    def for_repo_root(cls, root: Path) -> CaptureWorkflowPaths:
        return cls(
            root=root,
            scratchpad_manifest_path=root / "scratchpad" / "ladder_capture_manifest.json",
            fixture_manifest_path=root / "tests" / "fixtures" / "ladder_captures" / "manifest.json",
            captures_dir=root / "scratchpad" / "captures",
            fixtures_dir=root / "tests" / "fixtures" / "ladder_captures",
        )

    @classmethod
    def default(cls) -> CaptureWorkflowPaths:
        root = Path(__file__).resolve().parents[3]
        return cls.for_repo_root(root)


def default_verify_status_for_event(
    *,
    current_status: VerifyStatus,
    clipboard_event: str,
    pasted: bool | None = None,
    expected_match: bool | None = None,
) -> VerifyStatus:
    if clipboard_event == "copied":
        if pasted is None:
            raise ValueError("copied event requires pasted=True|False")
        if not pasted:
            return "blocked"
        if expected_match is None:
            raise ValueError("copied event with pasted=True requires expected_match=True|False")
        return "verified_pass" if expected_match else "verified_fail"
    if clipboard_event == "crash":
        return "blocked"
    if clipboard_event == "cancelled":
        return current_status
    raise ValueError(f"Unknown clipboard_event: {clipboard_event!r}")


class CaptureWorkflow:
    def __init__(
        self,
        *,
        paths: CaptureWorkflowPaths | None = None,
        copy_to_clipboard_fn: Callable[[bytes, int | None], None] = copy_to_clipboard,
        read_from_clipboard_fn: Callable[[], bytes] = read_from_clipboard,
        ensure_mdb_addresses_fn: Callable[[str, Sequence[str]], dict[str, Any]] = (
            ensure_addresses_exist
        ),
        find_click_hwnd_fn: Callable[[], int] = find_click_hwnd,
        find_click_database_fn: Callable[[int | None, int | None], str | None] = (
            find_click_database
        ),
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths or CaptureWorkflowPaths.default()
        self._copy_to_clipboard = copy_to_clipboard_fn
        self._read_from_clipboard = read_from_clipboard_fn
        self._ensure_mdb_addresses = ensure_mdb_addresses_fn
        self._find_click_hwnd = find_click_hwnd_fn
        self._find_click_database = find_click_database_fn
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def _now_iso(self) -> str:
        return (
            self._now_fn().astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )

    def _resolve_user_path(self, path_text: str) -> Path:
        path = Path(path_text)
        return path if path.is_absolute() else (self.paths.root / path)

    def _repo_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.paths.root.resolve()).as_posix()
        except ValueError:
            return str(path)

    def _load_manifest(self) -> dict[str, Any]:
        return capture_registry.load_manifest(self.paths.scratchpad_manifest_path)

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        capture_registry.save_manifest(self.paths.scratchpad_manifest_path, manifest)

    def _default_verify_result_path(self, label: str) -> Path:
        timestamp = self._now_fn().astimezone(UTC).strftime("%Y%m%d_%H%M%S")
        return self.paths.captures_dir / f"{label}_verify_back_{timestamp}.bin"

    def manifest_init(self, *, force: bool = False) -> dict[str, Any]:
        return capture_registry.init_manifest(self.paths.scratchpad_manifest_path, force=force)

    def entry_add(
        self,
        *,
        capture_type: str,
        label: str,
        scenario: str,
        description: str,
        rows: list[str],
        comments: list[str] | None = None,
        payload_source_mode: str = "shorthand",
        payload_file: str | None = None,
    ) -> dict[str, Any]:
        manifest = self._load_manifest()
        payload_source_file = payload_file if payload_source_mode == "file" else None
        all_rows = [format_comment_shorthand_row(text) for text in (comments or [])] + rows
        entry = capture_registry.add_entry(
            manifest,
            capture_label=label,
            capture_type=capture_type,
            scenario=scenario,
            description=description,
            rung_rows=all_rows,
            payload_source_mode=payload_source_mode,
            payload_source_file=payload_source_file,
            payload_file=payload_file,
            now_iso=self._now_iso(),
        )
        self._save_manifest(manifest)
        return entry

    def _auto_label_from_path(self, path: Path, *, label_prefix: str = "") -> str:
        stem = AUTO_LABEL_SANITIZE_RE.sub("_", path.stem).strip("_")
        if not stem:
            raise ValueError(f"Could not derive label from file name: {path.name!r}")
        return f"{label_prefix}{stem}"

    def _expand_payload_paths(
        self,
        *,
        files: list[str] | None = None,
        globs: list[str] | None = None,
    ) -> list[Path]:
        expanded: list[Path] = []
        seen: set[str] = set()

        for file_text in files or []:
            resolved = self._resolve_user_path(file_text)
            if not resolved.exists():
                raise FileNotFoundError(f"Payload file not found: {resolved}")
            if not resolved.is_file():
                raise ValueError(f"Payload path is not a file: {resolved}")
            key = str(resolved.resolve())
            if key not in seen:
                seen.add(key)
                expanded.append(resolved)

        for pattern in globs or []:
            pattern_path = Path(pattern)
            pattern_text = (
                str(pattern_path)
                if pattern_path.is_absolute()
                else str(self.paths.root / pattern_path)
            )
            matches = [Path(item) for item in glob.glob(pattern_text)]
            file_matches = [item for item in matches if item.is_file()]
            if not file_matches:
                raise FileNotFoundError(f"No files matched glob pattern: {pattern!r}")
            for item in file_matches:
                key = str(item.resolve())
                if key in seen:
                    continue
                seen.add(key)
                expanded.append(item)

        if not expanded:
            raise ValueError("Provide at least one --file or --glob")

        return expanded

    def entry_add_patch_batch(
        self,
        *,
        scenario: str,
        row: str,
        comments: list[str] | None = None,
        files: list[str] | None = None,
        globs: list[str] | None = None,
        label_prefix: str = "",
        description_prefix: str = "auto patch payload",
        skip_existing: bool = False,
    ) -> dict[str, Any]:
        if not scenario:
            raise ValueError("scenario must be non-empty")
        payload_paths = self._expand_payload_paths(files=files, globs=globs)
        manifest = self._load_manifest()
        created: list[str] = []
        skipped: list[str] = []
        scenario_rows = [format_comment_shorthand_row(text) for text in (comments or [])] + [row]

        for payload_path in payload_paths:
            repo_payload = self._repo_path(payload_path)
            label = self._auto_label_from_path(payload_path, label_prefix=label_prefix)
            description = f"{description_prefix}: {repo_payload}"
            try:
                capture_registry.add_entry(
                    manifest,
                    capture_label=label,
                    capture_type="patch",
                    scenario=scenario,
                    description=description,
                    rung_rows=scenario_rows,
                    payload_source_mode="file",
                    payload_source_file=repo_payload,
                    payload_file=repo_payload,
                    now_iso=self._now_iso(),
                )
                created.append(label)
            except ValueError as exc:
                if skip_existing and "capture_label already exists" in str(exc):
                    skipped.append(label)
                    continue
                raise

        if created:
            self._save_manifest(manifest)

        return {
            "scenario": scenario,
            "row": row,
            "comments": comments or [],
            "created_count": len(created),
            "created_labels": created,
            "skipped_count": len(skipped),
            "skipped_labels": skipped,
            "source_count": len(payload_paths),
        }

    def entry_list(
        self,
        *,
        capture_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        manifest = self._load_manifest()
        return capture_registry.list_entries(
            manifest, capture_type=capture_type, verify_status=status
        )

    def entry_show(self, *, label: str) -> dict[str, Any]:
        manifest = self._load_manifest()
        return capture_registry.copy_entry(capture_registry.find_entry(manifest, label))

    def entry_delete(
        self,
        *,
        label: str | None = None,
        scenario: str | None = None,
        yes: bool = False,
    ) -> dict[str, Any]:
        manifest = self._load_manifest()
        result = capture_registry.delete_entries(
            manifest,
            label=label,
            scenario=scenario,
            dry_run=(not yes),
        )
        if yes and result["deleted_count"] > 0:
            self._save_manifest(manifest)
        return result

    def entry_capture(self, *, label: str, output_file: str | None = None) -> dict[str, Any]:
        data = self._read_from_clipboard()
        output_path = (
            self._resolve_user_path(output_file)
            if output_file
            else (self.paths.captures_dir / f"{label}.bin")
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)

        manifest = self._load_manifest()
        updated = capture_registry.update_entry(
            manifest,
            label,
            payload_file=self._repo_path(output_path),
            now_iso=self._now_iso(),
        )
        self._save_manifest(manifest)
        return {
            "entry": updated,
            "payload_len": len(data),
            "payload_file": self._repo_path(output_path),
        }

    def _entry_rows_to_simple_csv(self, rows: list[str]) -> str:
        canonical_rows = [normalize_shorthand_row(row) for row in rows]
        if any(row.is_comment for row in canonical_rows):
            raise ValueError(
                "Shorthand payload mode does not support comment rows; use --payload-source file"
            )

        if len(canonical_rows) != 1:
            raise ValueError("Shorthand payload mode currently supports exactly one row")

        canonical = canonical_rows[0]
        if not canonical.af:
            raise ValueError("Shorthand payload mode requires a non-empty AF instruction")

        contacts = [
            token for token in canonical.conditions if token and token not in {"-", "|", "T"}
        ]
        if not contacts:
            raise ValueError("Shorthand payload mode requires at least one contact condition")

        return f"{','.join(contacts)},->,:,{canonical.af}"

    def _default_verify_source_mode(
        self, entry: dict[str, Any], requested_source: str | None
    ) -> str:
        if requested_source is not None:
            return requested_source

        if entry["capture_type"] == "native" and entry.get("payload_file"):
            return "file"

        return entry["payload_source_mode"]

    def _payload_bytes_for_source(
        self,
        entry: dict[str, Any],
        source_mode: str,
        *,
        header_seed: HeaderSeed | None = None,
    ) -> bytes:
        if source_mode == "shorthand":
            return ClickCodec().encode_rows(
                entry["rung_rows"],
                mode="strict",
                header_seed=header_seed,
            )

        if source_mode == "file":
            source_path_text = entry.get("payload_source_file") or entry.get("payload_file")
            if not source_path_text:
                raise ValueError("Entry has no payload_source_file or payload_file to load")
            source_path = self._resolve_user_path(source_path_text)
            if not source_path.exists():
                raise FileNotFoundError(f"Payload source file not found: {source_path}")
            return source_path.read_bytes()

        allowed = ", ".join(sorted(capture_registry.PAYLOAD_SOURCE_MODES))
        raise ValueError(f"Invalid source mode {source_mode!r}; expected one of [{allowed}]")

    def _seed_from_payload_file(self, path_text: str) -> HeaderSeed:
        path = self._resolve_user_path(path_text)
        if not path.exists():
            raise FileNotFoundError(f"Header seed source file not found: {path}")
        return HeaderSeed.from_payload(path.read_bytes())

    def _resolve_header_seed(
        self,
        *,
        manifest: dict[str, Any],
        source: str,
        seed_entry_label: str | None,
        seed_file: str | None,
    ) -> tuple[HeaderSeed, dict[str, Any]]:
        if source not in SEED_SOURCES:
            allowed = ", ".join(sorted(SEED_SOURCES))
            raise ValueError(f"seed_source must be one of [{allowed}]")

        if source == "scaffold":
            seed = HeaderSeed.from_scaffold()
            return (
                seed,
                {
                    "requested": source,
                    "source_used": "scaffold",
                    "warning": None,
                },
            )

        if source == "entry":
            if not seed_entry_label:
                raise ValueError("seed_source=entry requires --seed-entry-label")
            seed_entry = capture_registry.find_entry(manifest, seed_entry_label)
            seed_path_text = seed_entry.get("verify_result_file") or seed_entry.get("payload_file")
            if not seed_path_text:
                raise ValueError(
                    f"Seed entry {seed_entry_label!r} has no payload_file/verify_result_file"
                )
            seed = self._seed_from_payload_file(seed_path_text)
            return (
                seed,
                {
                    "requested": source,
                    "source_used": "entry",
                    "source_label": seed_entry_label,
                    "source_path": seed_path_text,
                    "warning": None,
                },
            )

        if source == "file":
            if not seed_file:
                raise ValueError("seed_source=file requires --seed-file")
            seed = self._seed_from_payload_file(seed_file)
            return (
                seed,
                {
                    "requested": source,
                    "source_used": "file",
                    "source_path": self._repo_path(self._resolve_user_path(seed_file)),
                    "warning": None,
                },
            )

        # source == "clipboard": try payload-derived seed, else deterministic scaffold fallback.
        try:
            clipboard_bytes = self._read_from_clipboard()
            seed = HeaderSeed.from_payload(clipboard_bytes)
            return (
                seed,
                {
                    "requested": source,
                    "source_used": "clipboard",
                    "warning": None,
                },
            )
        except Exception as exc:
            seed = HeaderSeed.from_scaffold()
            return (
                seed,
                {
                    "requested": source,
                    "source_used": "scaffold_fallback",
                    "warning": (
                        "Header seed fallback to scaffold because clipboard seed extraction "
                        f"failed: {exc}"
                    ),
                },
            )

    def _extract_operand_candidates(self, token: str) -> list[str]:
        text = token.strip().upper()
        if not text:
            return []

        out: list[str] = []
        for match in ADDRESS_RANGE_RE.finditer(text):
            out.append(match.group(1))
            out.append(match.group(2))
        for match in ADDRESS_TOKEN_RE.finditer(text):
            out.append(match.group(1))
        return out

    def _extract_row_operand_addresses(self, rows: Sequence[str]) -> list[str]:
        seen_keys: set[int] = set()
        parsed: list[str] = []

        for row in rows:
            canonical = normalize_shorthand_row(row)
            if canonical.is_comment:
                continue
            tokens = [*canonical.conditions, canonical.af]
            for token in tokens:
                for candidate in self._extract_operand_candidates(token):
                    try:
                        memory_type, address = parse_address(candidate)
                    except ValueError:
                        continue
                    addr_key = get_addr_key(memory_type, address)
                    if addr_key in seen_keys:
                        continue
                    seen_keys.add(addr_key)
                    parsed.append(format_address_display(memory_type, address))
        return parsed

    def _resolve_verify_mdb_path(self, mdb_path: str | None) -> Path:
        if mdb_path:
            resolved = self._resolve_user_path(mdb_path)
            if not resolved.exists():
                raise FileNotFoundError(f"verify MDB path not found: {resolved}")
            return resolved

        try:
            click_hwnd = self._find_click_hwnd()
        except Exception as exc:
            raise RuntimeError(
                "Could not auto-detect a running CLICK window. "
                "Open CLICK or pass --mdb-path <path-to-SC_.mdb>."
            ) from exc

        db_path = self._find_click_database(None, click_hwnd)
        if not db_path:
            raise FileNotFoundError(
                "Could not locate SC_.mdb for the active CLICK window. "
                "Pass --mdb-path <path-to-SC_.mdb>."
            )
        resolved = Path(db_path)
        if not resolved.exists():
            raise FileNotFoundError(f"Auto-detected SC_.mdb not found: {resolved}")
        return resolved

    def verify_prepare(
        self,
        *,
        label: str,
        source: str | None = None,
        seed_source: str = "clipboard",
        seed_entry_label: str | None = None,
        seed_file: str | None = None,
        owner_hwnd: int | None = None,
        ensure_mdb_addresses: bool = True,
        mdb_path: str | None = None,
    ) -> dict[str, Any]:
        manifest = self._load_manifest()
        current = capture_registry.find_entry(manifest, label)
        source_mode = self._default_verify_source_mode(current, source)
        seed_info: dict[str, Any] = {
            "requested": seed_source,
            "source_used": None,
            "applied": False,
            "warning": None,
        }
        header_seed: HeaderSeed | None = None
        has_comment = any(normalize_shorthand_row(r).is_comment for r in current["rung_rows"])
        if source_mode == "shorthand" and not has_comment:
            header_seed, seed_meta = self._resolve_header_seed(
                manifest=manifest,
                source=seed_source,
                seed_entry_label=seed_entry_label,
                seed_file=seed_file,
            )
            seed_info.update(seed_meta)
            seed_info["applied"] = True
            seed_info["header_05"] = f"0x{header_seed.profile_05:02X}"
            seed_info["header_11"] = f"0x{header_seed.profile_11:02X}"
            seed_info["header_17"] = f"0x{header_seed.family_17:02X}"
            seed_info["header_18"] = f"0x{header_seed.family_18:02X}"

        payload = self._payload_bytes_for_source(current, source_mode, header_seed=header_seed)

        mdb_ensure: dict[str, Any]
        if ensure_mdb_addresses:
            parsed_addresses = self._extract_row_operand_addresses(current["rung_rows"])
            resolved_mdb_path = self._resolve_verify_mdb_path(mdb_path)
            summary = self._ensure_mdb_addresses(str(resolved_mdb_path), parsed_addresses)
            mdb_ensure = {
                "enabled": True,
                "db_path": str(resolved_mdb_path),
                "requested_count": len(parsed_addresses),
                "inserted_count": 0,
                "existing_count": len(parsed_addresses),
                "parsed_addresses": parsed_addresses,
            }
            mdb_ensure.update(summary)
            mdb_ensure["enabled"] = True
            mdb_ensure.setdefault("parsed_addresses", parsed_addresses)
        else:
            mdb_ensure = {
                "enabled": False,
                "db_path": None,
                "requested_count": 0,
                "inserted_count": 0,
                "existing_count": 0,
                "parsed_addresses": [],
            }

        self._copy_to_clipboard(payload, owner_hwnd)

        updated = capture_registry.update_entry(
            manifest,
            label,
            verify_expected_rows=current["rung_rows"],
            now_iso=self._now_iso(),
        )
        self._save_manifest(manifest)
        return {
            "entry": updated,
            "source_mode": source_mode,
            "payload_len": len(payload),
            "seed": seed_info,
            "mdb_ensure": mdb_ensure,
        }

    def verify_complete(
        self,
        *,
        label: str,
        status: str,
        clipboard_event: str,
        note: str = "",
        rows: list[str] | None = None,
        result_file: str | None = None,
        clipboard_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        if status not in capture_registry.VERIFY_STATUSES:
            allowed = ", ".join(sorted(capture_registry.VERIFY_STATUSES))
            raise ValueError(f"status must be one of [{allowed}]")
        if clipboard_event not in capture_registry.VERIFY_EVENTS:
            allowed = ", ".join(sorted(capture_registry.VERIFY_EVENTS))
            raise ValueError(f"clipboard_event must be one of [{allowed}]")

        manifest = self._load_manifest()
        current = capture_registry.find_entry(manifest, label)

        verify_result_file: str | None = None
        verify_clipboard_len: int | None = None

        if clipboard_event == "copied":
            if clipboard_bytes is None and result_file is None:
                clipboard_bytes = self._read_from_clipboard()

            if clipboard_bytes is not None:
                output_path = (
                    self._resolve_user_path(result_file)
                    if result_file
                    else self._default_verify_result_path(label)
                )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(clipboard_bytes)
                verify_result_file = self._repo_path(output_path)
                verify_clipboard_len = len(clipboard_bytes)
            elif result_file is not None:
                output_path = self._resolve_user_path(result_file)
                if not output_path.exists():
                    raise FileNotFoundError(f"verify result file not found: {output_path}")
                verify_result_file = self._repo_path(output_path)
                verify_clipboard_len = len(output_path.read_bytes())
        elif result_file is not None:
            output_path = self._resolve_user_path(result_file)
            if not output_path.exists():
                raise FileNotFoundError(f"verify result file not found: {output_path}")
            verify_result_file = self._repo_path(output_path)

        updated = capture_registry.update_entry(
            manifest,
            label,
            verify_clipboard_event=clipboard_event,
            verify_status=status,
            verify_notes=note,
            verify_observed_rows=(rows if rows is not None else current["verify_observed_rows"]),
            verify_result_file=verify_result_file,
            verify_clipboard_len=verify_clipboard_len,
            now_iso=self._now_iso(),
        )
        self._save_manifest(manifest)
        return {"entry": updated}

    def _report_profile_row(self, entry: dict[str, Any]) -> dict[str, Any]:
        payload_text = entry.get("payload_file")
        if not payload_text:
            raise ValueError(f"Entry has no payload_file: {entry['capture_label']}")

        payload_path = self._resolve_user_path(payload_text)
        if not payload_path.exists():
            raise FileNotFoundError(f"Payload file not found: {payload_path}")

        raw = payload_path.read_bytes()
        data = raw[:PROFILE_REPORT_BUFFER_SIZE]

        cell_base = cell_offset(PROFILE_REPORT_CELL_ROW, PROFILE_REPORT_CELL_COLUMN)
        max_required_offset = max(
            cell_base + 0x1B,
            HEADER_ENTRY_BASE + 0x18,
            PROFILE_REPORT_TRAILER_OFFSET,
        )
        if len(data) <= max_required_offset:
            raise ValueError(
                f"Payload too short for profile report ({entry['capture_label']}): {len(raw)} bytes"
            )

        def hx(value: int) -> str:
            return f"0x{value:02X}"

        return {
            "capture_label": entry["capture_label"],
            "capture_type": entry["capture_type"],
            "scenario": entry["scenario"],
            "payload_file": payload_text,
            "record_len": len(raw),
            "cell_05": hx(data[cell_base + 0x05]),
            "cell_11": hx(data[cell_base + 0x11]),
            "cell_1a": hx(data[cell_base + 0x1A]),
            "cell_1b": hx(data[cell_base + 0x1B]),
            "header_05": hx(data[HEADER_ENTRY_BASE + 0x05]),
            "header_11": hx(data[HEADER_ENTRY_BASE + 0x11]),
            "header_17": hx(data[HEADER_ENTRY_BASE + 0x17]),
            "header_18": hx(data[HEADER_ENTRY_BASE + 0x18]),
            "trailer_0a59": hx(data[PROFILE_REPORT_TRAILER_OFFSET]),
        }

    def report_profile(
        self,
        *,
        label: str | None = None,
        all_entries: bool = False,
    ) -> list[dict[str, Any]]:
        if all_entries == (label is not None):
            raise ValueError("Specify exactly one of: --label or --all")

        manifest = self._load_manifest()
        if all_entries:
            entries = [entry for entry in manifest["entries"] if entry.get("payload_file")]
            if not entries:
                raise ValueError("No manifest entries with payload_file were found")
        else:
            if label is None:
                raise ValueError("--label is required when --all is not set")
            entries = [capture_registry.find_entry(manifest, label)]

        rows = [self._report_profile_row(entry) for entry in entries]
        rows.sort(key=lambda row: row["capture_label"])
        return rows

    def report_profile_csv(self, rows: list[dict[str, Any]]) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(PROFILE_REPORT_HEADER_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in PROFILE_REPORT_HEADER_FIELDS})
        return buf.getvalue()

    def _report_profile_columns_for_entry(
        self,
        entry: dict[str, Any],
        *,
        rows: list[int],
        cols: list[int],
        offsets: list[int],
    ) -> list[dict[str, Any]]:
        payload_text = entry.get("payload_file")
        if not payload_text:
            raise ValueError(f"Entry has no payload_file: {entry['capture_label']}")

        payload_path = self._resolve_user_path(payload_text)
        if not payload_path.exists():
            raise FileNotFoundError(f"Payload file not found: {payload_path}")

        raw = payload_path.read_bytes()
        data = raw[:PROFILE_REPORT_BUFFER_SIZE]

        max_required_offset = max(
            cell_offset(row, col) + rel for row in rows for col in cols for rel in offsets
        )
        if len(data) <= max_required_offset:
            raise ValueError(
                f"Payload too short for profile-columns report ({entry['capture_label']}): "
                f"{len(raw)} bytes"
            )

        def hx(value: int) -> str:
            return f"0x{value:02X}"

        results: list[dict[str, Any]] = []
        for row in rows:
            for col in cols:
                base = cell_offset(row, col)
                out: dict[str, Any] = {
                    "capture_label": entry["capture_label"],
                    "capture_type": entry["capture_type"],
                    "scenario": entry["scenario"],
                    "payload_file": payload_text,
                    "record_len": len(raw),
                    "row": row,
                    "column": col,
                }
                for rel in offsets:
                    out[f"cell_{rel:02x}"] = hx(data[base + rel])
                results.append(out)
        return results

    def report_profile_columns(
        self,
        *,
        label: str | None = None,
        all_entries: bool = False,
        rows: list[int] | None = None,
        cols: list[int] | None = None,
        offsets: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        if all_entries == (label is not None):
            raise ValueError("Specify exactly one of: --label or --all")

        rows = rows or list(PROFILE_COLUMNS_DEFAULT_ROWS)
        cols = cols or list(PROFILE_COLUMNS_DEFAULT_COLS)
        offsets = offsets or list(PROFILE_COLUMNS_DEFAULT_OFFSETS)

        manifest = self._load_manifest()
        if all_entries:
            entries = [entry for entry in manifest["entries"] if entry.get("payload_file")]
            if not entries:
                raise ValueError("No manifest entries with payload_file were found")
        else:
            if label is None:
                raise ValueError("--label is required when --all is not set")
            entries = [capture_registry.find_entry(manifest, label)]

        out: list[dict[str, Any]] = []
        for entry in entries:
            out.extend(
                self._report_profile_columns_for_entry(
                    entry,
                    rows=rows,
                    cols=cols,
                    offsets=offsets,
                )
            )
        out.sort(key=lambda row: (row["capture_label"], row["row"], row["column"]))
        return out

    def report_profile_columns_csv(
        self,
        rows: list[dict[str, Any]],
        *,
        offsets: list[int],
    ) -> str:
        fieldnames = [*PROFILE_COLUMNS_REPORT_BASE_FIELDS, *[f"cell_{rel:02x}" for rel in offsets]]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
        return buf.getvalue()

    def _prompt_yes_no(
        self,
        prompt: str,
        *,
        input_fn: Callable[[str], str],
        output_fn: Callable[[str], None],
        default: bool = False,
    ) -> bool:
        suffix = "[Y/n]" if default else "[y/N]"
        while True:
            raw = input_fn(f"{prompt} {suffix} ").strip().lower()
            if not raw:
                return default
            if raw in {"y", "yes"}:
                return True
            if raw in {"n", "no"}:
                return False
            output_fn("Please answer y or n.")

    def _prompt_status(
        self,
        *,
        default_status: str,
        input_fn: Callable[[str], str],
        output_fn: Callable[[str], None],
    ) -> str:
        allowed = sorted(capture_registry.VERIFY_STATUSES)
        if default_status not in capture_registry.VERIFY_STATUSES:
            raise ValueError(f"default status is invalid: {default_status!r}")
        prompt = f"Final verify status [{default_status}] ({', '.join(allowed)}): "
        while True:
            raw = input_fn(prompt).strip()
            status = raw or default_status
            if status in capture_registry.VERIFY_STATUSES:
                return status
            output_fn("Invalid status.")

    def _prompt_rows_override(
        self,
        *,
        expected_rows: list[str],
        input_fn: Callable[[str], str],
        output_fn: Callable[[str], None],
    ) -> list[str]:
        raw = input_fn(
            "Press Enter to keep expected rows, or type 'edit' to override rows: "
        ).strip()
        if raw.lower() != "edit":
            return expected_rows

        output_fn("Enter observed shorthand rows, one per line. Type 'end' when done.")
        rows: list[str] = []
        while True:
            line = input_fn("> ").strip()
            if line.lower() == "end":
                break
            if line:
                rows.append(line)
        if not rows:
            return expected_rows
        return capture_registry.canonicalize_rows(rows)

    def _prompt_rows_multiline(
        self,
        *,
        input_fn: Callable[[str], str],
        output_fn: Callable[[str], None],
        default_rows: list[str],
    ) -> list[str]:
        output_fn("Enter observed shorthand rows, one per line. Type 'end' when done.")
        rows: list[str] = []
        while True:
            line = input_fn("> ").strip()
            if line.lower() == "end":
                break
            if line:
                rows.append(line)
        if not rows:
            return default_rows
        return capture_registry.canonicalize_rows(rows)

    def verify_run_interactive(
        self,
        *,
        label: str,
        source: str | None = None,
        seed_source: str = "clipboard",
        seed_entry_label: str | None = None,
        seed_file: str | None = None,
        owner_hwnd: int | None = None,
        ensure_mdb_addresses: bool = True,
        mdb_path: str | None = None,
        status_default: str | None = None,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> dict[str, Any]:
        prepare = self.verify_prepare(
            label=label,
            source=source,
            seed_source=seed_source,
            seed_entry_label=seed_entry_label,
            seed_file=seed_file,
            owner_hwnd=owner_hwnd,
            ensure_mdb_addresses=ensure_mdb_addresses,
            mdb_path=mdb_path,
        )
        entry = prepare["entry"]
        expected_rows: list[str] = entry["verify_expected_rows"] or entry["rung_rows"]

        output_fn(f"Label: {entry['capture_label']}")
        output_fn(f"Type: {entry['capture_type']}")
        output_fn(f"Scenario: {entry['scenario']}")
        output_fn(f"Payload source: {prepare['source_mode']} ({prepare['payload_len']} bytes)")
        seed_info = prepare.get("seed", {})
        if seed_info.get("applied"):
            output_fn(
                "Header seed: "
                f"{seed_info.get('source_used')} "
                f"(+05={seed_info.get('header_05')} +11={seed_info.get('header_11')} "
                f"+17={seed_info.get('header_17')} +18={seed_info.get('header_18')})"
            )
        if seed_info.get("warning"):
            output_fn(f"Warning: {seed_info['warning']}")
        output_fn("Expected rows:")
        for row in expected_rows:
            output_fn(f"  {row}")

        while True:
            action = input_fn("Clipboard event ([c]opied / cra[x]h / [q]cancel): ").strip().lower()
            if action in {"c", "x", "q"}:
                break
            output_fn("Please enter c, x, or q.")

        if action == "c":
            clipboard_bytes = self._read_from_clipboard()
            pasted = self._prompt_yes_no(
                "Did Click paste the rung?", input_fn=input_fn, output_fn=output_fn
            )
            expected_match = False
            if pasted:
                expected_match = self._prompt_yes_no(
                    "Did pasted result match expected behavior?",
                    input_fn=input_fn,
                    output_fn=output_fn,
                )
            note = input_fn("Verification notes (optional): ").strip()
            observed_rows = self._prompt_rows_override(
                expected_rows=expected_rows,
                input_fn=input_fn,
                output_fn=output_fn,
            )
            default_status = status_default or default_verify_status_for_event(
                current_status=entry["verify_status"],
                clipboard_event="copied",
                pasted=pasted,
                expected_match=(expected_match if pasted else None),
            )
            final_status = self._prompt_status(
                default_status=default_status,
                input_fn=input_fn,
                output_fn=output_fn,
            )
            return self.verify_complete(
                label=label,
                status=final_status,
                clipboard_event="copied",
                note=note,
                rows=observed_rows,
                clipboard_bytes=clipboard_bytes,
            )

        if action == "x":
            note = input_fn("Crash notes: ").strip()
            if self._prompt_yes_no(
                "Do you want to enter observed rows?",
                input_fn=input_fn,
                output_fn=output_fn,
            ):
                observed_rows = self._prompt_rows_multiline(
                    input_fn=input_fn,
                    output_fn=output_fn,
                    default_rows=entry["verify_observed_rows"],
                )
            else:
                observed_rows = entry["verify_observed_rows"]
            default_status = status_default or default_verify_status_for_event(
                current_status=entry["verify_status"],
                clipboard_event="crash",
            )
            final_status = self._prompt_status(
                default_status=default_status,
                input_fn=input_fn,
                output_fn=output_fn,
            )
            return self.verify_complete(
                label=label,
                status=final_status,
                clipboard_event="crash",
                note=note,
                rows=observed_rows,
            )

        note = input_fn("Cancellation notes (optional): ").strip()
        default_status = status_default or default_verify_status_for_event(
            current_status=entry["verify_status"],
            clipboard_event="cancelled",
        )
        if status_default is None and self._prompt_yes_no(
            "Set status to blocked?",
            input_fn=input_fn,
            output_fn=output_fn,
            default=False,
        ):
            default_status = "blocked"
        final_status = self._prompt_status(
            default_status=default_status,
            input_fn=input_fn,
            output_fn=output_fn,
        )
        return self.verify_complete(
            label=label,
            status=final_status,
            clipboard_event="cancelled",
            note=note,
        )

    def _default_fixture_manifest(self) -> dict[str, Any]:
        return {
            "version": FIXTURE_MANIFEST_VERSION,
            "description": FIXTURE_MANIFEST_DESCRIPTION,
            "entries": [],
        }

    def _load_fixture_manifest(self) -> dict[str, Any]:
        if not self.paths.fixture_manifest_path.exists():
            return self._default_fixture_manifest()
        payload = json.loads(self.paths.fixture_manifest_path.read_text(encoding="utf-8"))
        if payload.get("version") != FIXTURE_MANIFEST_VERSION:
            raise ValueError(
                f"Fixture manifest version must be {FIXTURE_MANIFEST_VERSION}, "
                f"got {payload.get('version')!r}"
            )
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise ValueError("Fixture manifest entries must be a list")
        return payload

    def _save_fixture_manifest(self, manifest: dict[str, Any]) -> None:
        self.paths.fixture_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.fixture_manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )

    def _codec_generatable(self, payload: bytes) -> bool:
        codec = ClickCodec()
        try:
            decoded = codec.decode(payload)
            regenerated = codec.encode(decoded)
            return header_structural_equal(regenerated, payload) and (
                parse_wire_topology(regenerated) == parse_wire_topology(payload)
            )
        except Exception:
            return False

    def promote(
        self,
        *,
        label: str,
        fixture_file: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        manifest = self._load_manifest()
        entry = capture_registry.find_entry(manifest, label)

        promotable = entry["capture_type"] == "native" or entry["verify_status"] == "verified_pass"
        if not promotable:
            raise ValueError(
                "Promotion blocked: non-native entries require verify_status=verified_pass"
            )

        payload_text = entry.get("verify_result_file") or entry.get("payload_file")
        if not payload_text:
            raise ValueError("Promotion failed: no payload file (verify_result_file/payload_file)")
        payload_path = self._resolve_user_path(payload_text)
        if not payload_path.exists():
            raise FileNotFoundError(f"Payload file not found for promotion: {payload_path}")
        payload = payload_path.read_bytes()

        if fixture_file:
            fixture_path = (
                self._resolve_user_path(fixture_file)
                if Path(fixture_file).is_absolute()
                else self.paths.fixtures_dir / fixture_file
            )
        else:
            fixture_path = self.paths.fixtures_dir / f"{label}.bin"
        fixture_path.parent.mkdir(parents=True, exist_ok=True)

        if fixture_path.exists() and not overwrite:
            raise FileExistsError(
                f"Fixture already exists: {fixture_path}. Use --overwrite to replace."
            )
        fixture_path.write_bytes(payload)

        fixture_manifest = self._load_fixture_manifest()
        fixture_entries = fixture_manifest["entries"]

        promoted = {
            "fixture_file": fixture_path.name,
            "capture_label": entry["capture_label"],
            "scenario": entry["scenario"],
            "source": "scratchpad/captures",
            "description": entry["description"],
            "rung_rows": entry["rung_rows"],
            "verified": entry["verify_status"] == "verified_pass",
            "codec_generatable": self._codec_generatable(payload),
            "metadata_todo": not (entry["description"] and entry["rung_rows"]),
        }

        existing_idx = next(
            (i for i, row in enumerate(fixture_entries) if row.get("capture_label") == label),
            None,
        )
        if existing_idx is None:
            fixture_entries.append(promoted)
        else:
            fixture_entries[existing_idx] = promoted
        fixture_entries.sort(key=lambda row: row["fixture_file"])
        self._save_fixture_manifest(fixture_manifest)

        updated = capture_registry.update_entry(
            manifest,
            label,
            promoted_fixture_file=self._repo_path(fixture_path),
            now_iso=self._now_iso(),
        )
        self._save_manifest(manifest)
        return {
            "entry": updated,
            "fixture_entry": promoted,
            "fixture_file": self._repo_path(fixture_path),
        }


def run_tui(
    workflow: CaptureWorkflow | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    """Simple terminal wizard on top of capture_workflow operations."""
    engine = workflow or CaptureWorkflow()
    output_fn("ClickNick Ladder Capture TUI")

    while True:
        output_fn("")
        output_fn("1) List entries")
        output_fn("2) Capture native payload (guided)")
        output_fn("3) Verify run (Copied/Crash/Cancel)")
        output_fn("4) Promote entry")
        output_fn("5) Exit")
        choice = input_fn("Select an option: ").strip()

        if choice == "1":
            entries = engine.entry_list()
            if not entries:
                output_fn("No entries.")
                continue
            for row in entries:
                output_fn(
                    f"{row['capture_label']}: type={row['capture_type']} status={row['verify_status']}"
                )
            continue

        if choice == "2":
            try:
                native_entries = engine.entry_list(capture_type="native")
                pending = [row for row in native_entries if not row.get("payload_file")]
                if not pending:
                    output_fn("No pending native entries.")
                    continue

                output_fn(f"Pending native captures: {len(pending)}")
                captured = 0
                skipped = 0
                queue_stopped = False

                for index, entry in enumerate(pending, start=1):
                    label = entry["capture_label"]
                    output_fn("")
                    output_fn(f"[{index}/{len(pending)}] {label}")
                    output_fn(f"Scenario: {entry['scenario']}")
                    if entry["description"]:
                        output_fn(f"Description: {entry['description']}")
                    if entry["rung_rows"]:
                        output_fn("Rows:")
                        for row in entry["rung_rows"]:
                            output_fn(f"  {row}")

                    while True:
                        action = (
                            input_fn("Action ([Enter]/c capture, s skip, q quit): ").strip().lower()
                        )
                        if action in {"", "c", "s", "q"}:
                            break
                        output_fn("Please enter Enter/c, s, or q.")

                    if action == "s":
                        skipped += 1
                        continue
                    if action == "q":
                        queue_stopped = True
                        break

                    ready = (
                        input_fn(
                            "In Click: copy this rung now. Press Enter to capture (s skip, q quit): "
                        )
                        .strip()
                        .lower()
                    )
                    if ready in {"s", "skip"}:
                        skipped += 1
                        continue
                    if ready in {"q", "quit", "cancel"}:
                        queue_stopped = True
                        break

                    result = engine.entry_capture(label=label)
                    captured += 1
                    output_fn(f"Captured {result['payload_len']} bytes -> {result['payload_file']}")

                if queue_stopped:
                    remaining = len(
                        [
                            row
                            for row in engine.entry_list(capture_type="native")
                            if not row.get("payload_file")
                        ]
                    )
                    output_fn(
                        f"Queue stopped. captured={captured} skipped={skipped} remaining={remaining}"
                    )
                else:
                    output_fn(f"Queue complete. captured={captured} skipped={skipped} remaining=0")
            except Exception as exc:
                output_fn(f"Error: {exc}")
            continue

        if choice == "3":
            mode = input_fn("Verify mode ([l]abel / [g]uided queue / [q] cancel): ").strip().lower()
            if mode in {"q", "quit", "cancel"}:
                continue

            while True:
                source_raw = (
                    input_fn("Payload source override ([d]efault / [f]ile / [s]horthand): ")
                    .strip()
                    .lower()
                )
                if source_raw in {"", "d", "default"}:
                    source_override: str | None = None
                    break
                if source_raw in {"f", "file"}:
                    source_override = "file"
                    break
                if source_raw in {"s", "shorthand"}:
                    source_override = "shorthand"
                    break
                output_fn("Please enter d, f, or s.")

            if mode in {"", "l", "label"}:
                label = input_fn("Label: ").strip()
                if not label:
                    output_fn("Label is required.")
                    continue
                try:
                    result = engine.verify_run_interactive(
                        label=label,
                        source=source_override,
                        input_fn=input_fn,
                        output_fn=output_fn,
                    )
                    output_fn(f"Updated verify status: {result['entry']['verify_status']}")
                except Exception as exc:
                    output_fn(f"Error: {exc}")
                continue

            if mode in {"g", "guided", "queue"}:
                try:
                    scenario_filter = input_fn(
                        "Scenario filter (blank for all unverified entries): "
                    ).strip()
                    candidates = engine.entry_list(status="unverified")
                    if scenario_filter:
                        if scenario_filter.lower() == "today":
                            today_str = datetime.now(UTC).strftime("%Y-%m-%d")
                            candidates = [
                                row
                                for row in candidates
                                if row.get("updated_at", "").startswith(today_str)
                            ]
                        else:
                            needle = scenario_filter.lower()
                            candidates = [
                                row for row in candidates if needle in row["scenario"].lower()
                            ]
                    if not candidates:
                        output_fn("No unverified entries match filter.")
                        continue

                    output_fn(f"Pending verify entries: {len(candidates)}")
                    verified = 0
                    skipped = 0
                    queue_stopped = False

                    for index, entry in enumerate(candidates, start=1):
                        label = entry["capture_label"]
                        output_fn("")
                        output_fn(f"[{index}/{len(candidates)}] {label}")
                        output_fn(f"Type: {entry['capture_type']}")
                        output_fn(f"Scenario: {entry['scenario']}")
                        if entry["description"]:
                            output_fn(f"Description: {entry['description']}")
                        if entry["rung_rows"]:
                            output_fn("Rows:")
                            for row in entry["rung_rows"]:
                                output_fn(f"  {row}")

                        while True:
                            action = (
                                input_fn("Action ([Enter]/v verify, s skip, q quit): ")
                                .strip()
                                .lower()
                            )
                            if action in {"", "v", "s", "q"}:
                                break
                            output_fn("Please enter Enter/v, s, or q.")

                        if action == "s":
                            skipped += 1
                            continue
                        if action == "q":
                            queue_stopped = True
                            break

                        result = engine.verify_run_interactive(
                            label=label,
                            source=source_override,
                            input_fn=input_fn,
                            output_fn=output_fn,
                        )
                        verified += 1
                        output_fn(f"Updated verify status: {result['entry']['verify_status']}")

                    remaining = len(engine.entry_list(status="unverified"))
                    if queue_stopped:
                        output_fn(
                            f"Verify queue stopped. verified={verified} skipped={skipped} "
                            f"remaining_unverified={remaining}"
                        )
                    else:
                        output_fn(
                            f"Verify queue complete. verified={verified} skipped={skipped} "
                            f"remaining_unverified={remaining}"
                        )
                except Exception as exc:
                    output_fn(f"Error: {exc}")
                continue

            output_fn("Invalid verify mode.")
            continue

        if choice == "4":
            label = input_fn("Label: ").strip()
            fixture_file = input_fn("Fixture file (blank for <label>.bin): ").strip() or None
            overwrite = input_fn("Overwrite existing fixture? [y/N] ").strip().lower() in {
                "y",
                "yes",
            }
            try:
                result = engine.promote(label=label, fixture_file=fixture_file, overwrite=overwrite)
                output_fn(f"Promoted to {result['fixture_file']}")
            except Exception as exc:
                output_fn(f"Error: {exc}")
            continue

        if choice == "5":
            return 0

        output_fn("Invalid option.")
