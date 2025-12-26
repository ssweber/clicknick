"""Data source abstraction for the Address Editor.

Provides abstract base class and implementations for loading/saving
address data from different sources (MDB database, CSV files).
"""

from __future__ import annotations

import csv
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .address_model import AddressRow

# CSV column names (matching CLICK software export format)
CSV_COLUMNS = ["Address", "Nickname", "Data Type", "Initial Value", "Retentive", "Address Comment"]

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

# Data type code to string mapping (for saving)
DATA_TYPE_CODE_TO_STR: dict[int, str] = {
    0: "BIT",
    1: "INT",
    2: "INT2",
    3: "FLOAT",
    4: "HEX",
    6: "TXT",
}

# Regex for parsing address strings like "X001", "C100", "DS1000", "TD5"
ADDRESS_PATTERN = re.compile(r"^([A-Z]+)(\d+)$")


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
            from ..mdb_shared import find_click_database

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
        from .mdb_operations import MdbConnection, load_all_addresses

        with MdbConnection(self._db_path) as conn:
            return load_all_addresses(conn)

    def save_changes(self, rows: Sequence[AddressRow]) -> int:
        """Save dirty rows to the MDB database."""
        from .mdb_operations import MdbConnection, save_changes

        with MdbConnection(self._db_path) as conn:
            return save_changes(conn, rows)

    @property
    def supports_used_field(self) -> bool:
        """MDB has the Used field from the database."""
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
        from .address_model import (
            ADDRESS_RANGES,
            DEFAULT_RETENTIVE,
            MEMORY_TYPE_TO_DATA_TYPE,
            AddressRow,
            make_addr_key,
        )

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

                    addr_key = make_addr_key(mem_type, address)

                    addr_row = AddressRow(
                        memory_type=mem_type,
                        address=address,
                        nickname=nickname,
                        original_nickname=nickname,
                        comment=comment,
                        original_comment=comment,
                        used=False,  # CSV has no used field
                        exists_in_mdb=bool(
                            nickname or comment
                        ),  # Consider it "exists" if has content
                        data_type=data_type,
                        initial_value=initial_value,
                        original_initial_value=initial_value,
                        retentive=retentive,
                        original_retentive=retentive,
                    )

                    result[addr_key] = addr_row

        except (OSError, csv.Error):
            # Return empty dict on error
            return result

        return result

    def save_changes(self, rows: Sequence[AddressRow]) -> int:
        """Save changes to the CSV file.

        Rewrites the entire CSV with all rows that have content.

        Args:
            rows: Sequence of AddressRow objects

        Returns:
            Number of rows written
        """
        # Collect all rows with content (from all rows, not just dirty)
        rows_to_write = []
        for row in rows:
            # Write rows that have nickname or comment (or are marked as needing update)
            if row.nickname or row.comment or row.is_dirty:
                # Skip rows that are being deleted
                if row.needs_full_delete:
                    continue
                rows_to_write.append(row)

        # Sort by memory type order and address
        from .address_model import MEMORY_TYPE_ORDER

        type_order = {t: i for i, t in enumerate(MEMORY_TYPE_ORDER)}
        rows_to_write.sort(key=lambda r: (type_order.get(r.memory_type, 999), r.address))

        # Write CSV
        try:
            with open(self._csv_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=CSV_COLUMNS)
                writer.writeheader()

                for row in rows_to_write:
                    # Convert data type to string
                    data_type_str = DATA_TYPE_CODE_TO_STR.get(row.data_type, "")

                    # Format address with leading zeros for certain types
                    if row.memory_type in ("X", "Y"):
                        addr_str = f"{row.memory_type}{row.address:03d}"
                    else:
                        addr_str = f"{row.memory_type}{row.address}"

                    writer.writerow(
                        {
                            "Address": addr_str,
                            "Nickname": row.nickname,
                            "Data Type": data_type_str,
                            "Initial Value": row.initial_value,
                            "Retentive": "Yes" if row.retentive else "No",
                            "Address Comment": row.comment,
                        }
                    )

            return len(rows_to_write)

        except OSError:
            return 0
