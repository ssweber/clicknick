"""CDV file I/O for CLICK PLC DataView files.

CDV files are CSV files with UTF-16 encoding used by CLICK Programming Software
to store DataView configurations. Each file contains up to 100 monitored addresses.

File format:
- Encoding: UTF-16 LE with BOM
- Line 1: Header - "0,0,0" (no new values) or "-1,0,0" (has new values)
- Lines 2-101: Data rows - "Address,TypeCode[,NewValue]" or ",0" for empty
"""

from __future__ import annotations

from pathlib import Path

from .dataview_model import (
    MAX_DATAVIEW_ROWS,
    DataviewRow,
    create_empty_dataview,
    get_type_code_for_address,
)


def load_cdv(path: Path | str) -> tuple[list[DataviewRow], bool]:
    """Load a CDV file.

    Args:
        path: Path to the CDV file.

    Returns:
        Tuple of (rows, has_new_values) where:
        - rows: List of DataviewRow objects (always MAX_DATAVIEW_ROWS length)
        - has_new_values: True if the dataview has new values set

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file format is invalid.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CDV file not found: {path}")

    # Read file with UTF-16 encoding
    content = path.read_text(encoding="utf-16")
    lines = content.strip().split("\n")

    if not lines:
        raise ValueError(f"Empty CDV file: {path}")

    # Parse header line
    header = lines[0].strip()
    header_parts = [p.strip() for p in header.split(",")]
    if len(header_parts) < 1:
        raise ValueError(f"Invalid CDV header: {header}")

    # First value: 0 = no new values, -1 = has new values
    try:
        has_new_values = int(header_parts[0]) == -1
    except ValueError:
        has_new_values = False

    # Parse data rows
    rows = create_empty_dataview()
    data_lines = lines[1 : MAX_DATAVIEW_ROWS + 1]

    for i, line in enumerate(data_lines):
        if i >= MAX_DATAVIEW_ROWS:
            break

        line = line.strip()
        if not line:
            continue

        parts = [p.strip() for p in line.split(",")]

        # Empty row: ",0" or just ","
        if not parts[0]:
            continue

        # Parse address
        address = parts[0]
        rows[i].address = address

        # Parse type code
        if len(parts) > 1 and parts[1]:
            try:
                rows[i].type_code = int(parts[1])
            except ValueError:
                # Try to infer from address
                code = get_type_code_for_address(address)
                rows[i].type_code = code if code is not None else 0
        else:
            # Infer type code from address
            code = get_type_code_for_address(address)
            rows[i].type_code = code if code is not None else 0

        # Parse new value (if present and has_new_values flag is set)
        if len(parts) > 2 and parts[2]:
            rows[i].new_value = parts[2]

    return rows, has_new_values


def save_cdv(path: Path | str, rows: list[DataviewRow], has_new_values: bool) -> None:
    """Save a CDV file.

    Args:
        path: Path to save the CDV file.
        rows: List of DataviewRow objects (must be MAX_DATAVIEW_ROWS length).
        has_new_values: True if any rows have new values set.

    Raises:
        ValueError: If rows list is wrong length.
    """
    if len(rows) != MAX_DATAVIEW_ROWS:
        raise ValueError(f"Expected {MAX_DATAVIEW_ROWS} rows, got {len(rows)}")

    path = Path(path)

    # Build content
    lines: list[str] = []

    # Header line
    header_flag = -1 if has_new_values else 0
    lines.append(f"{header_flag},0,0")

    # Data rows
    for row in rows:
        if row.is_empty:
            lines.append(",0")
        else:
            if row.new_value:
                lines.append(f"{row.address},{row.type_code},{row.new_value}")
            else:
                lines.append(f"{row.address},{row.type_code}")

    # Join with newlines and add trailing newline
    content = "\n".join(lines) + "\n"

    # Write with UTF-16 encoding (includes BOM automatically)
    path.write_text(content, encoding="utf-16")


def export_cdv(path: Path | str, rows: list[DataviewRow], has_new_values: bool) -> None:
    """Export a CDV file to a new location.

    This is identical to save_cdv but semantically indicates exporting
    rather than saving to the original location.

    Args:
        path: Path to export the CDV file.
        rows: List of DataviewRow objects.
        has_new_values: True if any rows have new values set.
    """
    save_cdv(path, rows, has_new_values)


def get_dataview_folder(project_path: Path | str) -> Path | None:
    """Get the DataView folder for a CLICK project.

    The DataView folder is located at: {project_path}/CLICK ({unique_id})/DataView
    where {unique_id} is a hex identifier like "00010A98".

    Args:
        project_path: Path to the CLICK project folder.

    Returns:
        Path to the DataView folder, or None if not found.
    """
    project_path = Path(project_path)
    if not project_path.is_dir():
        return None

    # Look for CLICK (*) subdirectory
    for child in project_path.iterdir():
        if child.is_dir() and child.name.startswith("CLICK ("):
            dataview_path = child / "DataView"
            if dataview_path.is_dir():
                return dataview_path

    return None


def list_cdv_files(dataview_folder: Path | str) -> list[Path]:
    """List all CDV files in a DataView folder.

    Args:
        dataview_folder: Path to the DataView folder.

    Returns:
        List of Path objects for each CDV file, sorted by name.
    """
    folder = Path(dataview_folder)
    if not folder.is_dir():
        return []

    return sorted(folder.glob("*.cdv"), key=lambda p: p.stem.lower())
