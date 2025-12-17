"""Database operations for the Address Editor.

Provides connection management and CRUD operations for the MDB database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyodbc

from ..mdb_shared import create_access_connection, find_click_database
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
        """Create connection from Click window info.

        Args:
            click_pid: Process ID of the CLICK software
            click_hwnd: Window handle of the CLICK software

        Returns:
            MdbConnection instance configured for the database

        Raises:
            FileNotFoundError: If the database cannot be located
        """
        db_path = find_click_database(click_pid, click_hwnd)
        if not db_path:
            raise FileNotFoundError("Could not locate CLICK database")
        return cls(db_path)

    def connect(self) -> None:
        """Establish database connection.

        Raises:
            RuntimeError: If no Access drivers are available or connection fails
        """
        self._conn = create_access_connection(self.db_path)

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


def get_data_for_type(
    all_rows: dict[int, AddressRow], memory_type: str
) -> dict[int, dict[str, str | bool | int]]:
    """Extract data for a specific memory type from all_rows.

    This replaces load_nicknames_for_type for cases where all data
    is already loaded.

    Args:
        all_rows: Dict mapping AddrKey to AddressRow (from load_all_addresses)
        memory_type: The memory type to filter (X, Y, C, etc.)

    Returns:
        Dict mapping address (int) to dict with keys:
        nickname, comment, used, data_type, initial_value, retentive
    """
    result: dict[int, dict[str, str | bool | int]] = {}
    for row in all_rows.values():
        if row.memory_type == memory_type:
            result[row.address] = {
                "nickname": row.nickname,
                "comment": row.comment,
                "used": row.used,
                "data_type": row.data_type,
                "initial_value": row.initial_value,
                "retentive": row.retentive,
            }
    return result


def load_all_addresses(conn: MdbConnection) -> dict[int, AddressRow]:
    """Load ALL addresses from database.

    Args:
        conn: Active database connection

    Returns:
        Dict mapping AddrKey to AddressRow

    Raises:
        RuntimeError: If not connected
    """
    if not conn._conn:
        raise RuntimeError("Not connected to database")

    cursor = conn._conn.cursor()

    query = """
        SELECT AddrKey, MemoryType, Address, Nickname, Comment, Use, DataType, InitialValue, Retentive
        FROM address
        ORDER BY AddrKey
    """
    cursor.execute(query)

    result: dict[int, AddressRow] = {}
    for row in cursor.fetchall():
        (
            addr_key,
            memory_type,
            address,
            nickname,
            comment,
            used,
            data_type,
            initial_value,
            retentive,
        ) = row

        # Get default values for this memory type
        default_data_type = MEMORY_TYPE_TO_DATA_TYPE.get(memory_type, 0)
        default_retentive = DEFAULT_RETENTIVE.get(memory_type, False)

        nickname_str = nickname or ""
        comment_str = comment or ""
        initial_value_str = initial_value or ""
        data_type_val = data_type if data_type is not None else default_data_type
        retentive_val = bool(retentive) if retentive is not None else default_retentive

        result[addr_key] = AddressRow(
            memory_type=memory_type,
            address=int(address),
            nickname=nickname_str,
            original_nickname=nickname_str,
            comment=comment_str,
            original_comment=comment_str,
            used=bool(used),
            exists_in_mdb=True,
            data_type=data_type_val,
            initial_value=initial_value_str,
            original_initial_value=initial_value_str,
            retentive=retentive_val,
            original_retentive=retentive_val,
        )

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
