"""CDV file helpers for ClickNick DataView workflows."""

from __future__ import annotations

from pathlib import Path

from pyclickplc.dataview import check_cdv_file as check_cdv_file
from pyclickplc.dataview import load_cdv as load_cdv
from pyclickplc.dataview import save_cdv as save_cdv


def export_cdv(
    path: Path | str,
    rows,
    has_new_values: bool,
    header: str | None = None,
) -> None:
    """Export a CDV file to a new location."""
    save_cdv(path, rows, has_new_values, header)


def get_dataview_folder(project_path: Path | str) -> Path | None:
    """Get the DataView folder for a CLICK project."""
    project_path = Path(project_path)
    if not project_path.is_dir():
        return None

    for child in project_path.iterdir():
        if child.is_dir() and child.name.startswith("CLICK ("):
            dataview_path = child / "DataView"
            if dataview_path.is_dir():
                return dataview_path

    return None


def list_cdv_files(dataview_folder: Path | str) -> list[Path]:
    """List all CDV files in a DataView folder sorted case-insensitively."""
    folder = Path(dataview_folder)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.cdv"), key=lambda p: p.stem.lower())


def check_cdv_files(project_path: Path | str) -> tuple[list[str], int]:
    """Verify all CDV files in a project's DataView folder."""
    issues: list[str] = []
    files_checked = 0

    try:
        dataview_folder = get_dataview_folder(project_path)
        if dataview_folder is None:
            return issues, files_checked

        for cdv_path in list_cdv_files(dataview_folder):
            files_checked += 1
            issues.extend(check_cdv_file(cdv_path))
    except Exception as exc:
        issues.append(f"CDV: Error accessing dataview folder - {exc}")

    return issues, files_checked
