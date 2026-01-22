"""Database operations for the Address Editor.

Provides connection management and CRUD operations for the MDB database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyodbc

from ..models.address_row import AddressRow
from ..models.constants import DEFAULT_RETENTIVE, MEMORY_TYPE_TO_DATA_TYPE, DataType
from .mdb_shared import create_access_connection, find_click_database

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

    # Note: We don't need to select keys that match the defaults strictly,
    # but selecting them allows us to handle overrides correctly.
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

        # Handle DB Nulls and Defaults
        # If DB DataType is NULL, fallback to the hardcoded default for that memory type
        if data_type is None:
            final_data_type = MEMORY_TYPE_TO_DATA_TYPE.get(memory_type, DataType.BIT)
        else:
            final_data_type = data_type

        # If DB Retentive is NULL, fallback to hardcoded default
        if retentive is None:
            final_retentive = DEFAULT_RETENTIVE.get(memory_type, False)
        else:
            final_retentive = bool(retentive)

        # Create the row.
        # __post_init__ will automatically set original_nickname = nickname, etc.
        result[addr_key] = AddressRow(
            memory_type=memory_type,
            address=int(address),
            nickname=nickname or "",
            comment=comment or "",
            used=bool(used),
            data_type=final_data_type,
            initial_value=initial_value or "",
            retentive=final_retentive,
        )

    cursor.close()
    return result


def _delete_rows(cursor, rows: list[AddressRow]) -> int:
    """Helper: Delete rows regardless of existence."""
    # We can use executemany here for performance since the logic is simple
    params = [(row.addr_key,) for row in rows]
    cursor.executemany("DELETE FROM address WHERE AddrKey = ?", params)
    return len(rows)  # Assuming success if no exception raised


def _upsert_rows(cursor, rows: list[AddressRow]) -> int:
    """Helper: Defensively Insert or Update rows."""
    modified_count = 0

    for row in rows:
        # DEFENSIVE: Ignore 'exists_in_mdb' flag. Check the DB directly.
        # This prevents "Duplicate Key" errors if our state is out of sync.
        cursor.execute("SELECT Count(*) FROM address WHERE AddrKey = ?", (row.addr_key,))
        count = cursor.fetchone()[0]

        if count > 0:
            # UPDATE
            cursor.execute(
                """
                UPDATE address 
                SET Nickname = ?, Comment = ?, InitialValue = ?, Retentive = ? 
                WHERE AddrKey = ?
                """,
                (row.nickname, row.comment, row.initial_value, row.retentive, row.addr_key),
            )
        else:
            # INSERT
            cursor.execute(
                """
                INSERT INTO address (
                    AddrKey, MemoryType, Address, DataType, 
                    Nickname, Comment, InitialValue, Retentive
                )
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

    return modified_count


def save_changes(conn: MdbConnection, rows: Sequence[AddressRow]) -> int:
    """Save dirty rows to database defensively.

    Splits operations into Deletes and Upserts (Insert/Update) to handle
    state synchronization issues robustly.
    """
    if not conn._conn:
        raise RuntimeError("Not connected to database")

    # 1. Sort rows by intent
    to_delete = []
    to_upsert = []

    for row in rows:
        # Use existing logic to determine intent
        if row.needs_full_delete(is_dirty=True):
            to_delete.append(row)
        else:
            to_upsert.append(row)

    cursor = conn._conn.cursor()
    total_modified = 0

    try:
        # 2. Handle Deletions (Batchable)
        if to_delete:
            total_modified += _delete_rows(cursor, to_delete)

        # 3. Handle Upserts (Defensive Check-then-Act)
        if to_upsert:
            total_modified += _upsert_rows(cursor, to_upsert)

        conn._conn.commit()
        return total_modified

    except Exception:
        conn._conn.rollback()
        raise
    finally:
        cursor.close()
