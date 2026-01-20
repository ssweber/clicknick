"""Data source abstraction for the Address Editor.

Provides abstract base class and implementations for loading/saving
address data from different sources (MDB database, CSV files).
"""

from __future__ import annotations

import csv
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..models.address_row import AddressRow, get_addr_key
from ..models.constants import (
    ADDRESS_RANGES,
    DEFAULT_RETENTIVE,
    MEMORY_TYPE_BASES,
    MEMORY_TYPE_TO_DATA_TYPE,
)
from ..utils.mdb_operations import (
    MdbConnection,
    find_click_database,
    load_all_addresses,
    save_changes,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# CSV column names (matching CLICK software export format)
CSV_COLUMNS = ["Address", "Data Type", "Nickname", "Initial Value", "Retentive", "Address Comment"]

# Data type string to code mapping
DATA_TYPE_STR_TO_CODE: dict[str, int] = {
    "BIT": 0,
    "INT": 1,
    "INT2": 2,
    "FLOAT": 3,
    "HEX": 4,
    "TXT": 6,
    "TEXT": 6,  # Alias
}

# Data type code to string mapping (for saving csv)
DATA_TYPE_CODE_TO_STR: dict[int, str] = {
    0: "BIT",
    1: "INT",
    2: "INT2",
    3: "FLOAT",
    4: "HEX",
    6: "TEXT",  # Alias
}

# Regex for parsing address strings like "X001", "C100", "DS1000", "TD5"
ADDRESS_PATTERN = re.compile(r"^([A-Z]+)(\d+)$")


def load_addresses_from_mdb_dump(csv_path: str) -> dict[int, AddressRow]:
    """Load addresses from MDB-format CSV (CLICK Address.csv export).

    The CLICK software exports Address.csv in MDB format with columns:
    AddrKey, MemoryType, Address, DataType, Nickname, Use, InitialValue, Retentive, Comment

    Args:
        csv_path: Path to MDB-format CSV (e.g., Address.csv from CLICK temp folder)

    Returns:
        Dict mapping AddrKey (int) to AddressRow
    """
    result: dict[int, AddressRow] = {}

    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            # Skip rows without nicknames or comments (empty entries)
            nickname = row.get("Nickname", "").strip()
            comment = row.get("Comment", "").strip()
            if not nickname and not comment:
                continue

            mem_type = row.get("MemoryType", "").strip()
            if mem_type not in ADDRESS_RANGES:
                continue

            try:
                address = int(row.get("Address", "0"))
            except ValueError:
                continue

            # Parse data type
            try:
                data_type = int(row.get("DataType", "0"))
            except ValueError:
                data_type = MEMORY_TYPE_TO_DATA_TYPE.get(mem_type, 0)

            # Parse retentive (0 or 1)
            retentive_raw = row.get("Retentive", "").strip().lower()
            default_retentive = DEFAULT_RETENTIVE.get(mem_type, False)
            retentive = retentive_raw in (1, "1") if retentive_raw else default_retentive

            initial_value = row.get("InitialValue", "").strip()

            addr_key = get_addr_key(mem_type, address)

            addr_row = AddressRow(
                memory_type=mem_type,
                address=address,
                nickname=nickname,
                comment=comment,
                used=False,  # MDB dump doesn't reliably have this
                exists_in_mdb=True,
                data_type=data_type,
                initial_value=initial_value,
                retentive=retentive,
            )

            result[addr_key] = addr_row

    return result


class DataSource(ABC):
    """Abstract base class for address data sources.

    All data sources must implement loading and saving addresses,
    and provide a file path for file monitoring.
    """

    @property
    @abstractmethod
    def file_path(self) -> str:
        """Return the path to the data file for monitoring."""

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

    Loads addresses from a CSV file in CLICK software export format.
    Supports reading and writing, but has no 'Used' field information.
    """

    def __init__(self, csv_path: str):
        """Initialize CSV data source.

        Args:
            csv_path: Path to the CSV file
        """
        self._csv_path = csv_path

    @property
    def file_path(self) -> str:
        """Return the path to the CSV file."""
        return self._csv_path

    @property
    def supports_used_field(self) -> bool:
        """CSV has no 'Used' field."""
        return False

    def _parse_address(self, addr_str: str) -> tuple[str, int] | None:
        """Parse an address string like 'X001' into (memory_type, address).

        Args:
            addr_str: Address string from CSV (e.g., "X001", "C100", "DS1000")

        Returns:
            Tuple of (memory_type, address) or None if parsing fails
        """
        match = ADDRESS_PATTERN.match(addr_str.strip().upper())
        if not match:
            return None
        return match.group(1), int(match.group(2))

    def load_all_addresses(self) -> dict[int, AddressRow]:
        """Load all addresses from the CSV file.

        Returns:
            Dict mapping AddrKey (int) to AddressRow
        """
        result: dict[int, AddressRow] = {}

        # First, load all rows from CSV
        try:
            with open(self._csv_path, newline="", encoding="utf-8") as csvfile:
                reader = csv.DictReader(csvfile)

                # Verify required columns exist
                if reader.fieldnames is None:
                    return result
                missing = set(CSV_COLUMNS) - set(reader.fieldnames)
                if missing:
                    # Try to continue with what we have
                    pass

                for row in reader:
                    addr_str = row.get("Address", "").strip()
                    if not addr_str:
                        continue

                    parsed = self._parse_address(addr_str)
                    if not parsed:
                        continue

                    mem_type, address = parsed

                    # Skip if memory type not recognized
                    if mem_type not in ADDRESS_RANGES:
                        continue

                    # Get data type (default based on memory type)
                    default_data_type = MEMORY_TYPE_TO_DATA_TYPE.get(mem_type, 0)
                    data_type_str = row.get("Data Type", "").strip().upper()
                    data_type = DATA_TYPE_STR_TO_CODE.get(data_type_str, default_data_type)

                    # Get retentive
                    default_retentive = DEFAULT_RETENTIVE.get(mem_type, False)
                    retentive_str = row.get("Retentive", "").strip()
                    retentive = (
                        retentive_str.lower() == "yes" if retentive_str else default_retentive
                    )

                    # Get other fields
                    nickname = row.get("Nickname", "").strip()
                    comment = row.get("Address Comment", "").strip()
                    initial_value = row.get("Initial Value", "").strip()

                    addr_key = get_addr_key(mem_type, address)

                    addr_row = AddressRow(
                        memory_type=mem_type,
                        address=address,
                        nickname=nickname,
                        comment=comment,
                        used=False,  # CSV has no used field
                        exists_in_mdb=True,
                        data_type=data_type,
                        initial_value=initial_value,
                        retentive=retentive,
                    )

                    result[addr_key] = addr_row

        except (OSError, csv.Error):
            # Return empty dict on error
            return result

        return result

    def save_changes(self, rows: Sequence[AddressRow]) -> int:
        """Save to the CSV file.

        Rewrites the entire CSV with all rows that have content.
        """
        # Collect all rows with content (CSV rewrites entire file)
        rows_to_write = [row for row in rows if row.has_content]

        # Sort by memory type order and address
        rows_to_write.sort(
            key=lambda r: (MEMORY_TYPE_BASES.get(r.memory_type, 0xFFFFFFFF), r.address)
        )

        try:
            with open(self._csv_path, "w", newline="", encoding="utf-8") as csvfile:
                # 1. Write the Header manually
                # assuming CSV_COLUMNS is a list like ["Address", "Data Type", ...]
                csvfile.write(",".join(CSV_COLUMNS) + "\n")

                # Helper to format fields that MUST be quoted
                def format_quoted(text):
                    if text is None:
                        return '""'
                    # Escape existing double-quotes by doubling them (CSV standard)
                    escaped_text = str(text).replace('"', '""')
                    return f'"{escaped_text}"'

                for row in rows_to_write:
                    # Convert data type to string
                    data_type_str = DATA_TYPE_CODE_TO_STR.get(row.data_type, "")

                    # Format initial value: use "0" for numeric types when empty, "" for TXT
                    if row.initial_value:
                        initial_value_str = str(row.initial_value)
                    elif row.data_type == 6:  # TXT
                        initial_value_str = ""
                    else:
                        initial_value_str = "0"

                    # 2. Construct the line manually
                    # We leave Address, DataType, InitialValue, and Retentive RAW.
                    # We wrap Nickname and Comment in our format_quoted helper.
                    line_parts = [
                        row.display_address,  # Handles XD/YD formatting (XD0u, XD1-8)
                        data_type_str,
                        format_quoted(row.nickname),
                        initial_value_str,
                        "Yes" if row.retentive else "No",
                        format_quoted(row.comment),
                    ]

                    # Join with commas and write
                    csvfile.write(",".join(line_parts) + "\n")

            return len(rows_to_write)

        except OSError:
            return 0


def convert_mdb_csv_to_user_csv(source_path: str, dest_path: str) -> None:
    """Convert MDB-format CSV (CLICK export) to user-format CSV.

    Loads the MDB-format CSV as AddressRows, then saves using CsvDataSource
    to ensure proper formatting.

    Args:
        source_path: Path to MDB-format CSV (e.g., Address.csv from CLICK temp folder)
        dest_path: Path to write user-format CSV
    """
    # Load as AddressRows
    addresses = load_addresses_from_mdb_dump(source_path)

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
