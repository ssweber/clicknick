"""Data source abstraction for the Address Editor.

Provides abstract base class and implementations for loading/saving
address data from different sources (MDB database, CSV files).
"""

from __future__ import annotations

import csv
import os
import stat
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from pyclickplc.addresses import get_addr_key, parse_address
from pyclickplc.banks import (
    BANKS,
    DEFAULT_RETENTIVE,
    MEMORY_TYPE_BASES,
    MEMORY_TYPE_TO_DATA_TYPE,
    DataType,
)
from pyclickplc.nicknames import CSV_COLUMNS, DATA_TYPE_CODE_TO_STR, DATA_TYPE_STR_TO_CODE

from ..models.address_row import AddressRow
from ..utils.mdb_operations import (
    MdbConnection,
    find_click_database,
    load_all_addresses,
    save_changes,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# A nickname CSV must have these columns; without them it is not a nickname CSV
REQUIRED_COLUMNS = ("Address", "Nickname")

# Retentive as CLICK writes it (Yes/No) and as a spreadsheet may (1/0, True/False)
_RETENTIVE_ON = ("yes", "true", "1")

# The AddressRow field each nickname CSV column sets
COLUMN_FIELDS = {
    "Data Type": "data_type",
    "Nickname": "nickname",
    "Initial Value": "initial_value",
    "Retentive": "retentive",
    "Address Comment": "comment",
}


def _initial_value(raw: str, data_type: int) -> str:
    """A TXT initial value is kept as written (a space is a value); others are trimmed."""
    return raw if data_type == DataType.TXT else raw.strip()


def read_mdb_csv(csv_path: str) -> dict[int, AddressRow]:
    """Load addresses from MDB-format CSV (CLICK Address.csv export).

    The CLICK software exports Address.csv in MDB format with columns:
    AddrKey, MemoryType, Address, DataType, Nickname, Use, InitialValue, Retentive, Comment

    CLICK writes it as UTF-8 with a BOM. Rows are kept when they hold anything
    (AddressRow.has_content), as the database path keeps them.

    Args:
        csv_path: Path to MDB-format CSV (e.g., Address.csv from CLICK temp folder)

    Returns:
        Dict mapping AddrKey (int) to AddressRow
    """
    result: dict[int, AddressRow] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            mem_type = (row.get("MemoryType") or "").strip()
            if mem_type not in BANKS:
                continue

            try:
                address = int(row.get("Address") or "0")
            except ValueError:
                continue

            # Parse data type
            try:
                data_type = int(row.get("DataType") or "0")
            except ValueError:
                data_type = MEMORY_TYPE_TO_DATA_TYPE.get(mem_type, 0)

            # Parse retentive (0 or 1)
            retentive_raw = (row.get("Retentive") or "").strip()
            default_retentive = DEFAULT_RETENTIVE.get(mem_type, False)
            retentive = retentive_raw == "1" if retentive_raw else default_retentive

            addr_row = AddressRow(
                memory_type=mem_type,
                address=address,
                nickname=row.get("Nickname") or "",
                comment=row.get("Comment") or "",
                used=False,  # MDB dump doesn't reliably have this
                data_type=data_type,
                initial_value=_initial_value(row.get("InitialValue") or "", data_type),
                retentive=retentive,
            )
            if addr_row.has_content:
                result[get_addr_key(mem_type, address)] = addr_row

    return result


def _quoted(text: str) -> str:
    """Quoted, as CLICK writes every Nickname and Address Comment."""
    return '"' + text.replace('"', '""') + '"'


def _bare(text: str) -> str:
    """Unquoted, as CLICK writes the other columns, unless it holds a delimiter or quote.

    Leading or trailing whitespace is quoted too, so a reader that trims bare
    cells keeps it (a TXT initial value of one space).
    """
    special = any(char in text for char in ',"\r\n') or text != text.strip()
    return _quoted(text) if special else text


def _is_blank(row: dict[str | None, str | list[str] | None]) -> bool:
    """A row with nothing in any cell, such as a spreadsheet's trailing ``,,,,,``."""
    cells = [
        cell for value in row.values() for cell in (value if isinstance(value, list) else [value])
    ]
    return not any((cell or "").strip() for cell in cells)


def _read_nickname_csv(
    csv_path: str, required: Sequence[str]
) -> tuple[dict[int, AddressRow], frozenset[str]]:
    """Rows of a nickname CSV, and the fields its columns set.

    Raises ValueError when the file is not a nickname CSV it can read: a
    *required* column missing, a row whose Address is not a CLICK address (such
    as CLICK's own Address.csv, whose Address column holds numbers), not UTF-8,
    or not CSV.
    """
    name = Path(csv_path).name
    result: dict[int, AddressRow] = {}
    # Excel's "CSV UTF-8" starts the file with a BOM; CLICK's export has none
    with open(csv_path, newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)
        try:
            columns = reader.fieldnames
            if columns is None:
                raise ValueError(f"{name} is empty")
            missing = [column for column in required if column not in columns]
            if missing:
                raise ValueError(f"{name} has no {' or '.join(missing)} column")
            fields = frozenset(
                field for column, field in COLUMN_FIELDS.items() if column in columns
            )

            for row in reader:
                if _is_blank(row):
                    continue
                text = row.get("Address") or ""
                try:
                    mem_type, address = parse_address(text)
                except ValueError:
                    raise ValueError(
                        f"{name} line {reader.line_num}: Address {text!r} is not a CLICK address"
                    ) from None

                default_data_type = MEMORY_TYPE_TO_DATA_TYPE.get(mem_type, 0)
                data_type_str = (row.get("Data Type") or "").strip().upper()
                data_type = DATA_TYPE_STR_TO_CODE.get(data_type_str, default_data_type)

                default_retentive = DEFAULT_RETENTIVE.get(mem_type, False)
                retentive_str = (row.get("Retentive") or "").strip()
                retentive = (
                    retentive_str.lower() in _RETENTIVE_ON if retentive_str else default_retentive
                )

                result[get_addr_key(mem_type, address)] = AddressRow(
                    memory_type=mem_type,
                    address=address,
                    nickname=row.get("Nickname") or "",
                    comment=row.get("Address Comment") or "",
                    used=False,  # CSV has no used field
                    data_type=data_type,
                    initial_value=_initial_value(row.get("Initial Value") or "", data_type),
                    retentive=retentive,
                )
        except UnicodeDecodeError as exc:
            raise ValueError(f"{name} is not UTF-8 text: {exc}") from exc
        except csv.Error as exc:
            raise ValueError(f"{name} line {reader.line_num}: {exc}") from exc
    return result, fields


def _is_read_only(path: Path) -> bool:
    try:
        attributes = getattr(os.stat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_READONLY) or not os.access(path, os.W_OK)


def _write_file(path: Path, data: str) -> None:
    """Write *data* to *path*, keeping an existing file's identity and attributes.

    The text is encoded before the file is opened, so an encoding error leaves
    it as it was. An existing file is overwritten in place and truncated to the
    new length rather than recreated, so a Hidden file still saves and stays
    Hidden. A program that only reads the file (Explorer's preview pane,
    antivirus, OneDrive) does not stop the write; one that locks it, such as
    Excel, does.
    """
    encoded = data.encode("utf-8")
    try:
        if path.exists():
            with open(path, "r+b") as csvfile:
                csvfile.write(encoded)
                csvfile.truncate()
        else:
            with open(path, "xb") as csvfile:
                csvfile.write(encoded)
    except PermissionError as exc:
        if _is_read_only(path):
            raise PermissionError(f"{path.name} is read-only.") from exc
        raise PermissionError(
            f"{path.name} is open in another program (Excel?); close it and save again."
        ) from exc


class DataSource(ABC):
    """Abstract base class for address data sources.

    All data sources must implement loading and saving addresses,
    and provide a file path for file monitoring.
    """

    @property
    @abstractmethod
    def file_path(self) -> str:
        """Return the path to the data file for monitoring."""

    @property
    @abstractmethod
    def is_database(self) -> bool:
        """Return True if this is CLICK's project database (vs an exported CSV)."""

    @abstractmethod
    def load_all_addresses(self) -> dict[int, AddressRow]:
        """Load all addresses from the data source.

        Returns:
            Dict mapping AddrKey (int) to AddressRow
        """

    @abstractmethod
    def save_changes(self, rows: Sequence[AddressRow]) -> int:
        """Save dirty rows to the data source.

        Args:
            rows: Sequence of AddressRow objects (dirty ones will be saved)

        Returns:
            Number of rows modified
        """

    @property
    def is_read_only(self) -> bool:
        """Return True if this data source is read-only."""
        return False

    @property
    def supports_used_field(self) -> bool:
        """Return True if the data source has a 'Used' field."""
        return True


class CsvDataSource(DataSource):
    """Data source backed by CSV file.

    Reads and writes the CSV in the form CLICK exports it: columns
    ``CSV_COLUMNS``, Nickname and Address Comment always quoted, CRLF line ends.
    Has no 'Used' field information.
    """

    def __init__(self, csv_path: str, *, required: Sequence[str] = REQUIRED_COLUMNS):
        """Initialize CSV data source.

        Args:
            csv_path: Path to the CSV file
            required: Columns the file must have to load (Import from CSV needs
                only Address)
        """
        self._csv_path = csv_path
        self._required = tuple(required)
        self._fields: frozenset[str] = frozenset()
        # Why the file could not be read the last time it was loaded
        self._unreadable: str | None = None

    @property
    def file_path(self) -> str:
        """Return the path to the CSV file."""
        return self._csv_path

    @property
    def is_database(self) -> bool:
        return False

    @property
    def supports_used_field(self) -> bool:
        """CSV has no 'Used' field."""
        return False

    @property
    def fields(self) -> frozenset[str]:
        """The AddressRow fields the file has a column for, as of the last load.

        A field the file has no column for holds its default in every row read.
        """
        return self._fields

    def load_all_addresses(self) -> dict[int, AddressRow]:
        """Load all addresses from the CSV file.

        Raises:
            ValueError: The file is not a nickname CSV ClickNick can read; Save
                refuses to overwrite it until a load succeeds again.
            OSError: The file cannot be opened.

        Returns:
            Dict mapping AddrKey (int) to AddressRow
        """
        try:
            rows, self._fields = _read_nickname_csv(self._csv_path, self._required)
        except ValueError as exc:
            self._unreadable = str(exc)
            raise
        self._unreadable = None
        return rows

    def save_changes(self, rows: Sequence[AddressRow]) -> int:
        """Save to the CSV file.

        Rewrites the entire CSV with all rows that have content.

        Raises:
            ValueError: The last load found a file it could not read; it is
                left as it is.
            OSError: The file cannot be written, such as while Excel holds it open.
        """
        if self._unreadable is not None:
            raise ValueError(
                f"Not saved: {Path(self._csv_path).name} changed on disk and can no "
                f"longer be read ({self._unreadable})."
            )

        # Collect all rows with content (CSV rewrites entire file)
        rows_to_write = [row for row in rows if row.has_content]

        # Sort by memory type order and address
        rows_to_write.sort(
            key=lambda r: (MEMORY_TYPE_BASES.get(r.memory_type, 0xFFFFFFFF), r.address)
        )

        lines = [",".join(CSV_COLUMNS)]
        for row in rows_to_write:
            # A defaulted numeric is written "0", as CLICK does; TXT's default is empty
            if row.initial_value:
                initial_value_str = str(row.initial_value)
            elif row.data_type == DataType.TXT:
                initial_value_str = ""
            else:
                initial_value_str = "0"

            line_parts = [
                row.display_address,  # XD/YD as CLICK shows them (XD0u, XD1-8)
                DATA_TYPE_CODE_TO_STR.get(row.data_type, ""),
                _quoted(row.nickname),
                _bare(initial_value_str),
                "Yes" if row.retentive else "No",
                _quoted(row.comment),
            ]
            lines.append(",".join(line_parts))

        _write_file(Path(self._csv_path), "".join(line + "\r\n" for line in lines))
        return len(rows_to_write)


def convert_mdb_csv_to_user_csv(source_path: str, dest_path: str) -> None:
    """Convert MDB-format CSV (CLICK export) to user-format CSV.

    Loads the MDB-format CSV as AddressRows, then saves using CsvDataSource
    to ensure proper formatting.

    Args:
        source_path: Path to MDB-format CSV (e.g., Address.csv from CLICK temp folder)
        dest_path: Path to write user-format CSV
    """
    # Load as AddressRows
    addresses = read_mdb_csv(source_path)

    # Save using CsvDataSource (reuses existing save logic)
    csv_source = CsvDataSource(dest_path)
    csv_source.save_changes(list(addresses.values()))


class MdbDataSource(DataSource):
    """Data source backed by CLICK MDB (Access) database.

    Wraps the existing mdb_operations module functionality.
    """

    def __init__(
        self,
        click_pid: int | None = None,
        click_hwnd: int | None = None,
        db_path: str | None = None,
    ):
        """Initialize MDB data source.

        Args:
            click_pid: Process ID of CLICK software (used with click_hwnd)
            click_hwnd: Window handle of CLICK software (used with click_pid)
            db_path: Direct path to database (alternative to pid/hwnd)

        Raises:
            ValueError: If neither db_path nor (click_pid, click_hwnd) provided
            FileNotFoundError: If database cannot be located
        """
        if db_path:
            self._db_path = db_path
        elif click_pid is not None and click_hwnd is not None:
            db_path = find_click_database(click_pid, click_hwnd)
            if not db_path:
                raise FileNotFoundError("Could not locate CLICK database")
            self._db_path = db_path
        else:
            raise ValueError("Must provide either db_path or (click_pid, click_hwnd)")

    @property
    def file_path(self) -> str:
        """Return the path to the MDB file."""
        return self._db_path

    @property
    def is_database(self) -> bool:
        return True

    def load_all_addresses(self) -> dict[int, AddressRow]:
        """Load all addresses from the MDB database."""
        with MdbConnection(self._db_path) as conn:
            return load_all_addresses(conn)

    def save_changes(self, rows: Sequence[AddressRow]) -> int:
        """Save rows to the MDB database.

        Caller is responsible for passing only dirty rows.
        """
        if not rows:
            return 0

        with MdbConnection(self._db_path) as conn:
            return save_changes(conn, rows)

    @property
    def supports_used_field(self) -> bool:
        """MDB has the Used field from the database."""
        return True
