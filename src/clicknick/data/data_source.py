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

from pyclickplc.addresses import AddressRecord, get_addr_key
from pyclickplc.banks import (
    BANKS,
    DEFAULT_RETENTIVE,
    MEMORY_TYPE_TO_DATA_TYPE,
    DataType,
)
from pyclickplc.nicknames import CSV_ENCODING, REQUIRED_COLUMNS, format_csv, read_csv

from ..models.address_row import AddressRow
from ..utils.mdb_operations import (
    MdbConnection,
    find_click_database,
    load_all_addresses,
    save_changes,
    stored_row,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# The AddressRow field each nickname CSV column sets
COLUMN_FIELDS = {
    "Data Type": "data_type",
    "Nickname": "nickname",
    "Initial Value": "initial_value",
    "Retentive": "retentive",
    "Address Comment": "comment",
}


def _initial_value(raw: str, data_type: int) -> str:
    """Return *raw* unchanged for a TXT initial value (a space is a value), trimmed otherwise."""
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


def _row(record: AddressRecord) -> AddressRow:
    """Convert a *record* that pyclickplc read into the Address Editor's row.

    A CSV has no Used column.
    """
    return AddressRow(
        memory_type=record.memory_type,
        address=record.address,
        nickname=record.nickname,
        comment=record.comment,
        used=False,
        data_type=int(record.data_type),
        initial_value=record.initial_value,
        retentive=record.retentive,
    )


def _record(row: AddressRow) -> AddressRecord:
    """Convert the content of *row* into the record that pyclickplc writes."""
    return AddressRecord(
        memory_type=row.memory_type,
        address=row.address,
        nickname=row.nickname,
        comment=row.comment,
        initial_value=row.initial_value,
        retentive=row.retentive,
        data_type=row.data_type,
    )


def _is_read_only(path: Path) -> bool:
    try:
        attributes = getattr(os.stat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_READONLY) or not os.access(path, os.W_OK)


def _write_file(path: Path, data: str, encoding: str = CSV_ENCODING) -> None:
    """Write *data* to *path* in *encoding*, keeping an existing file's identity and attributes.

    This function encodes the text before it opens the file. An encoding error therefore
    leaves the file as it was. It overwrites an existing file in place and truncates it to
    the new length instead of recreating it. A Hidden file therefore still saves and stays
    Hidden. A program that only reads the file does not stop the write. Examples are
    Explorer's preview pane, antivirus and OneDrive. A program that locks the file, such as
    Excel, does stop it.
    """
    encoded = data.encode(encoding)
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
            raise PermissionError(
                f"Could not save {path.name}, because the file is read-only. Clear its "
                "Read-only attribute and save again."
            ) from exc
        raise PermissionError(
            f"{path.name} is open in another program, such as Excel. Close it and save again."
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

    @abstractmethod
    def stored_row(self, row: AddressRow) -> AddressRow:
        """Return *row* as this data source holds it after ``save_changes`` writes it.

        The store takes the result as its base row after a Sync, so that the next read of
        the data source changes nothing. A row that the data source does not keep, because
        ``save_changes`` deletes it or leaves it out, comes back with an empty initial value.
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

    Reads the CSV with pyclickplc's ``read_csv`` and writes it with its
    ``format_csv``, in the form CLICK exports it: Nickname and Address Comment
    always quoted, CRLF line ends. pyrung reads the workspace's
    ``nicknames.csv`` with the same reader. Has no 'Used' field information.
    """

    def __init__(
        self,
        csv_path: str,
        *,
        required: Sequence[str] = REQUIRED_COLUMNS,
        encoding: str = CSV_ENCODING,
    ):
        """Initialize CSV data source.

        Args:
            csv_path: Path to the CSV file
            encoding: The encoding that a save writes. The default is cp1252, as CLICK
                exports it. ClickNick writes every nickname CSV in cp1252, and a load
                reads either encoding.
            required: Columns the file must have to load (Import from CSV needs
                only Address)
        """
        self._csv_path = csv_path
        self._required = tuple(required)
        self._encoding = encoding
        self._fields: frozenset[str] = frozenset()
        # The reason the file could not be read the last time it was loaded
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
        """Return the AddressRow fields that the file has a column for, as of the last load.

        Every row read has the default for a field that the file has no column for.
        """
        return self._fields

    def load_all_addresses(self) -> dict[int, AddressRow]:
        """Load all addresses from the CSV file.

        Raises:
            ValueError: The file is not a nickname CSV that ``read_csv`` can read. The
                message names the file and, for a row, its line. Save refuses to
                overwrite the file until a load succeeds again.
            OSError: The file cannot be opened.

        Returns:
            Dict mapping AddrKey (int) to AddressRow
        """
        try:
            records = read_csv(self._csv_path, required=self._required)
        except ValueError as exc:
            self._unreadable = str(exc)
            raise
        self._unreadable = None
        self._fields = frozenset(
            field for column, field in COLUMN_FIELDS.items() if column in records.columns
        )
        return {addr_key: _row(record) for addr_key, record in records.items()}

    def stored_row(self, row: AddressRow) -> AddressRow:
        """Return *row* as the CSV file reads back.

        ``format_csv`` writes 0 for an empty initial value of any data type but TXT, and
        ``read_csv`` reads it back as '0'. ``save_changes`` leaves out a row with no content.
        A CSV row is never Used. The rows that ``save_changes`` leaves out are therefore the
        rows that a save to SC_.mdb deletes, and the same rule fits both.
        """
        return stored_row(row)

    def save_changes(self, rows: Sequence[AddressRow]) -> int:
        """Save to the CSV file.

        Rewrites the entire CSV with all rows that have content.

        Raises:
            ValueError: The last load found a file it could not read; it is
                left as it is. It is also raised if a nickname, comment or initial
                value has a character that cp1252 does not have. The message names
                the address. The file is left as it is.
            OSError: The file cannot be written, such as while Excel holds it open.
        """
        if self._unreadable is not None:
            raise ValueError(
                f"Could not save {Path(self._csv_path).name}, because ClickNick can no "
                "longer read the file on disk. Fix the file, and ClickNick reads it again. "
                f"The error was: {self._unreadable}"
            )

        # The whole file is rewritten, with every row that has content
        records = [_record(row) for row in rows if row.has_content]
        _write_file(Path(self._csv_path), format_csv(records), self._encoding)
        return len(records)


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
                raise FileNotFoundError(
                    "ClickNick found no SC_.mdb in CLICK's temporary folder for this window."
                )
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

    def stored_row(self, row: AddressRow) -> AddressRow:
        """Return *row* as SC_.mdb holds it after ``save_changes`` writes it."""
        return stored_row(row)

    @property
    def supports_used_field(self) -> bool:
        """MDB has the Used field from the database."""
        return True
