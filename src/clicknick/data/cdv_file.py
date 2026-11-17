"""Find the DataView folder of a CLICK project and verify its CDV files."""

from __future__ import annotations

from pathlib import Path

from pyclickplc.dataview import check_cdv_file

from ..utils.click_temp import click_temp_dir, temp_root


def click_dataview_folder(hwnd: int) -> Path | None:
    """Return the DataView folder of the CLICK window *hwnd*, or None if it has none.

    Only that window's ``CLICK (hwnd)`` folder counts. Another window's folder, or one that
    a crash left behind, holds another project's .cdv files.
    """
    folder = click_temp_dir(hwnd) / "DataView"
    return folder if folder.is_dir() else None


def csv_dataview_folder(csv_path: Path | str) -> Path | None:
    """Return the folder that holds the CSV *csv_path*, or None if it is gone or is CLICK's own.

    A CSV copied into a ``CLICK (hwnd)`` temp folder lives only as long as that window, so
    its folder is not a place to open or save .cdv files.
    """
    folder = Path(csv_path).parent
    if not folder.is_dir():
        return None
    root = temp_root()
    if any(p.parent == root and p.name.startswith("CLICK (") for p in (folder, *folder.parents)):
        return None
    return folder


def list_cdv_files(dataview_folder: Path | str) -> list[Path]:
    """List all CDV files in a DataView folder sorted case-insensitively."""
    folder = Path(dataview_folder)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.cdv"), key=lambda p: p.stem.lower())


def check_cdv_files(dataview_folder: Path | None) -> tuple[list[str], int]:
    """Verify all CDV files in a DataView folder. Check none if *dataview_folder* is None."""
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
