"""Database operations for the Address Editor.

Provides connection management and CRUD operations for the MDB database.
Reuses connection logic from NicknameManager.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyodbc

from .address_model import DEFAULT_RETENTIVE, MEMORY_TYPE_TO_DATA_TYPE, AddressRow

if TYPE_CHECKING:
    from collections.abc import Sequence


class MdbConnection:
    """Wrapper for MDB database operations."""

    def __init__(self, db_path: str):
        """Initialize with a database path.

        Args:
            db_path: Full path to the SC_.mdb file
        """
        self.db_path = db_path
        self._conn: pyodbc.Connection | None = None

    @classmethod
    def from_click_window(cls, click_pid: int, click_hwnd: int) -> MdbConnection:
        """Create connection using existing NicknameManager logic.

        Args:
            click_pid: Process ID of the CLICK software
            click_hwnd: Window handle of the CLICK software

        Returns:
            MdbConnection instance configured for the database

        Raises:
            FileNotFoundError: If the database cannot be located
        """
        # Import here to avoid circular dependency
        from ..nickname_manager import NicknameManager

        # Reuse the existing database finder
        temp_manager = NicknameManager()
        db_path = temp_manager._find_click_database(click_pid, click_hwnd)
        if not db_path:
            raise FileNotFoundError("Could not locate CLICK database")
        return cls(db_path)

    def connect(self) -> None:
        """Establish database connection.

        Raises:
            RuntimeError: If no Access drivers are available or connection fails
        """
        # Import here to avoid circular dependency
        from ..nickname_manager import NicknameManager

        # Reuse driver detection logic from NicknameManager
        temp_manager = NicknameManager()
        drivers = temp_manager.get_available_access_drivers()

        if not drivers:
            raise RuntimeError("No Microsoft Access ODBC drivers available")

        # Preferred driver order
        preferred_drivers = [
            "Microsoft Access Driver (*.mdb, *.accdb)",
            "Microsoft Access Driver (*.mdb)",
            "Microsoft Access Driver",
        ]

        # Try drivers in order of preference
        driver_errors = []
        for driver in preferred_drivers + [d for d in drivers if d not in preferred_drivers]:
            try:
                conn_str = f"DRIVER={{{driver}}};DBQ={self.db_path};"
                self._conn = pyodbc.connect(conn_str)
                return
            except pyodbc.Error as e:
                driver_errors.append(f"Driver '{driver}' failed: {e}")
                continue

        error_msg = "Failed to connect with any Access driver:\n" + "\n".join(driver_errors)
        raise RuntimeError(error_msg)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def is_connected(self) -> bool:
        """Check if the connection is active."""
        return self._conn is not None

    def __enter__(self) -> MdbConnection:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


def load_nicknames_for_type(
    conn: MdbConnection, memory_type: str
) -> dict[int, dict[str, str | bool | int]]:
    """Load existing address data for a specific memory type.

    Args:
        conn: Active database connection
        memory_type: The memory type to load (X, Y, C, etc.)

    Returns:
        Dict mapping address (int) to dict with keys:
        nickname, comment, used, data_type, initial_value, retentive

    Raises:
        RuntimeError: If not connected
    """
    if not conn._conn:
        raise RuntimeError("Not connected to database")

    cursor = conn._conn.cursor()

    # Query ALL rows for this memory type (don't filter - rows may exist for "used" tracking)
    # Include DataType, InitialValue, and Retentive fields
    query = """
        SELECT MemoryType, Address, Nickname, Comment, Use, DataType, InitialValue, Retentive
        FROM address
        ORDER BY Address
    """
    cursor.execute(query)

    # Get default values for this memory type
    default_data_type = MEMORY_TYPE_TO_DATA_TYPE.get(memory_type, 0)
    default_retentive = DEFAULT_RETENTIVE.get(memory_type, False)

    result: dict[int, dict[str, str | bool | int]] = {}
    for row in cursor.fetchall():
        mem_type, address, nickname, comment, used, data_type, initial_value, retentive = row
        if mem_type == memory_type:
            result[int(address)] = {
                "nickname": nickname or "",
                "comment": comment or "",
                "used": bool(used),
                "data_type": data_type if data_type is not None else default_data_type,
                "initial_value": initial_value or "",
                "retentive": bool(retentive) if retentive is not None else default_retentive,
            }

    cursor.close()
    return result


def load_all_nicknames(conn: MdbConnection) -> dict[int, str]:
    """Load ALL nicknames from database for uniqueness validation.

    Args:
        conn: Active database connection

    Returns:
        Dict mapping AddrKey to nickname

    Raises:
        RuntimeError: If not connected
    """
    if not conn._conn:
        raise RuntimeError("Not connected to database")

    cursor = conn._conn.cursor()

    query = """
        SELECT AddrKey, Nickname
        FROM address
        WHERE Nickname <> ''
    """
    cursor.execute(query)

    result = {}
    for row in cursor.fetchall():
        addr_key, nickname = row
        result[addr_key] = nickname

    cursor.close()
    return result


def save_changes(conn: MdbConnection, rows: Sequence[AddressRow]) -> int:
    """Save all dirty rows to database.

    Performs INSERT, UPDATE, DELETE, or clear based on row state.

    Args:
        conn: Active database connection
        rows: List of AddressRow objects to save (will filter to dirty ones)

    Returns:
        Number of rows modified

    Raises:
        RuntimeError: If not connected
        Exception: If any database operation fails (transaction rolled back)
    """
    if not conn._conn:
        raise RuntimeError("Not connected to database")

    cursor = conn._conn.cursor()
    modified_count = 0

    try:
        for row in rows:
            if row.needs_full_delete:
                # Delete the entire row from database
                cursor.execute(
                    """
                    DELETE FROM address WHERE AddrKey = ?
                """,
                    (row.addr_key,),
                )
                modified_count += 1

            elif row.needs_insert:
                # Insert new row with all fields
                cursor.execute(
                    """
                    INSERT INTO address (AddrKey, MemoryType, Address, DataType, Nickname, Comment, InitialValue, Retentive)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        row.addr_key,
                        row.memory_type,
                        row.address,
                        row.data_type,
                        row.nickname,
                        row.comment,
                        row.initial_value,
                        row.retentive,
                    ),
                )
                modified_count += 1

            elif row.needs_update:
                # Update existing row (all editable fields)
                cursor.execute(
                    """
                    UPDATE address SET Nickname = ?, Comment = ?, InitialValue = ?, Retentive = ? WHERE AddrKey = ?
                """,
                    (row.nickname, row.comment, row.initial_value, row.retentive, row.addr_key),
                )
                modified_count += 1

            elif row.needs_delete:
                # Clear nickname (set to empty string, keep row for other fields)
                cursor.execute(
                    """
                    UPDATE address SET Nickname = '' WHERE AddrKey = ?
                """,
                    (row.addr_key,),
                )
                modified_count += 1

        conn._conn.commit()

        # Mark all modified rows as saved
        for row in rows:
            if row.is_dirty:
                row.mark_saved()

        return modified_count

    except Exception:
        conn._conn.rollback()
        raise
    finally:
        cursor.close()
