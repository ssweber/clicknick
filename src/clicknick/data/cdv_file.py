"""DataView folder discovery and CDV verification for a CLICK project."""

from __future__ import annotations

from pathlib import Path

from pyclickplc.dataview import check_cdv_file

from ..utils.click_temp import click_temp_dir


def click_dataview_folder(hwnd: int) -> Path | None:
    """The DataView folder of the CLICK window *hwnd*, or None when it has none.

    Only that window's ``CLICK (hwnd)`` folder: another window's, or one a
    crash left behind, holds another project's .cdv files.
    """
    folder = click_temp_dir(hwnd) / "DataView"
    return folder if folder.is_dir() else None


def list_cdv_files(dataview_folder: Path | str) -> list[Path]:
    """List all CDV files in a DataView folder sorted case-insensitively."""
    folder = Path(dataview_folder)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.cdv"), key=lambda p: p.stem.lower())


def check_cdv_files(dataview_folder: Path | None) -> tuple[list[str], int]:
    """Verify all CDV files in a DataView folder (none checked without one)."""
    issues: list[str] = []
    files_checked = 0

    try:
        if dataview_folder is None:
            return issues, files_checked

        for cdv_path in list_cdv_files(dataview_folder):
            files_checked += 1
            issues.extend(check_cdv_file(cdv_path))
    except Exception as exc:
        issues.append(f"CDV: Error accessing dataview folder - {exc}")

    return issues, files_checked
