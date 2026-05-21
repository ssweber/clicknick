"""Orchestrates the export→convert pipeline for simulation.

Pure Python, no tkinter.  Chains ``program_save()`` and
``ladder_to_pyrung_project()`` to produce a pyrung project inside
the Click project's temp folder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SimulateResult:
    """Result of a prepare/rebuild operation."""

    project_dir: Path
    csv_dir: Path
    file_count: int
    tag_to_address: dict[str, str] = field(default_factory=dict)
    address_to_tag: dict[str, str] = field(default_factory=dict)


def _write_nicknames_csv(csv_dir: Path, db_path: Path | None) -> Path | None:
    """Write nicknames.csv from MDB.  Returns path or None."""
    if db_path is None:
        return None
    nick_dest = csv_dir / "nicknames.csv"
    try:
        from ..data.data_source import CsvDataSource
        from ..utils.mdb_operations import MdbConnection, load_all_addresses

        with MdbConnection(str(db_path)) as conn:
            all_rows = load_all_addresses(conn)
        CsvDataSource(str(nick_dest)).save_changes(list(all_rows.values()))
        return nick_dest
    except Exception:
        return None


def _build_address_map(
    nickname_map: dict[str, str] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Build bidirectional tag↔address maps.

    pyrung's DAP adapter keys ``tagValues`` — and resolves ``force``/``patch``
    targets — by the Tag's runtime name, which is the *raw* Click nickname.
    The Python-identifier sanitization pyrung codegen applies only renames
    generated source variables, never the runtime tag, so nicknames are mapped
    verbatim.  Addresses with no nickname become tags named after the address
    itself; those are resolved by identity at lookup time rather than enumerated
    here.
    """
    tag_to_addr: dict[str, str] = {}
    addr_to_tag: dict[str, str] = {}

    if not nickname_map:
        return tag_to_addr, addr_to_tag

    for address, nickname in nickname_map.items():
        tag = (nickname or "").strip()
        if not tag:
            continue
        addr_upper = address.upper()
        tag_to_addr[tag] = addr_upper
        addr_to_tag[addr_upper] = tag

    return tag_to_addr, addr_to_tag


def prepare(
    scr_folder: Path,
    db_path: Path | None = None,
    *,
    nickname_map: dict[str, str] | None = None,
) -> SimulateResult:
    """Export Scr*.tmp → CSV → pyrung project.

    The output lands in ``scr_folder / "pyrung_project" / {csv,project}``.
    *nickname_map* is ``{display_address: nickname}`` from AddressStore.

    Returns a :class:`SimulateResult` with paths and address↔tag maps.
    """
    base = scr_folder / "pyrung_project"
    csv_dir = base / "csv"
    project_dir = base / "project"

    csv_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    from ..ladder.program import program_save

    program_save(scr_folder, csv_dir)

    nickname_csv = _write_nicknames_csv(csv_dir, db_path)

    from pyrung.click import ladder_to_pyrung_project

    files = ladder_to_pyrung_project(
        csv_dir,
        nickname_csv=nickname_csv,
        output_dir=project_dir,
    )

    tag_to_addr, addr_to_tag = _build_address_map(nickname_map)

    return SimulateResult(
        project_dir=project_dir,
        csv_dir=csv_dir,
        file_count=len(files),
        tag_to_address=tag_to_addr,
        address_to_tag=addr_to_tag,
    )


def rebuild(
    scr_folder: Path,
    db_path: Path | None = None,
    *,
    nickname_map: dict[str, str] | None = None,
) -> SimulateResult:
    """Re-run the export pipeline, overwriting files in place."""
    return prepare(scr_folder, db_path, nickname_map=nickname_map)
