"""Shared MDB/Access database utilities.

Provides common functions for locating and connecting to Access databases
used by both NicknameManager and the Address Editor.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyodbc

from ..utils.win32_utils import WIN32

PREFERRED_ACCESS_DRIVERS = [
    "Microsoft Access Driver (*.mdb, *.accdb)",
    "Microsoft Access Driver (*.mdb)",
    "Microsoft Access Driver",
]

# CSV-only mode flag - when True, has_access_driver() returns False
_CSV_ONLY_MODE = False


def set_csv_only_mode(enabled: bool) -> None:
    """Enable or disable CSV-only mode (for testing fallback without ODBC)."""
    global _CSV_ONLY_MODE
    _CSV_ONLY_MODE = enabled


def get_available_access_drivers() -> list[str]:
    """Get list of available Microsoft Access ODBC drivers.

    Returns:
        List of available Access driver names
    """
    try:
        return [driver for driver in pyodbc.drivers() if "Access" in driver]
    except Exception as e:
        print(f"Error checking ODBC drivers: {e}")
        return []


def has_access_driver() -> bool:
    """Check if any Microsoft Access ODBC driver is available."""
    if _CSV_ONLY_MODE:
        return False
    return len(get_available_access_drivers()) > 0


def find_click_database(click_pid: int | None = None, click_hwnd: int | None = None) -> str | None:
    """Find the CLICK Programming Software's Access database file.

    Args:
        click_pid: Process ID of the CLICK software
        click_hwnd: Window handle of the CLICK software

    Returns:
        Path to the database file or None if not found
    """
    try:
        # Get the window handle if we don't have it
        if click_pid and not click_hwnd:
            click_hwnd = WIN32.get_hwnd_by_pid(click_pid)

        if click_hwnd:
            # Convert window handle to uppercase hex string without '0x' prefix
            hwnd_hex = format(click_hwnd, "08X")

            # Build the expected database path
            username = os.environ.get("USERNAME")
            db_path = Path(f"C:/Users/{username}/AppData/Local/Temp/CLICK ({hwnd_hex})/SC_.mdb")

            if db_path.exists():
                print(f"Found database: {db_path}")
                return str(db_path)

        return None

    except Exception as e:
        print(f"Error finding database: {e}")
        return None


def find_fallback_csv(click_hwnd: int | None = None) -> Path | None:
    """Find Address.csv in the CLICK temp folder as fallback when ODBC unavailable.

    The CLICK software generates Address.csv in the same folder as SC_.mdb
    when a project is loaded.

    Args:
        click_hwnd: Window handle of the CLICK software

    Returns:
        Path to Address.csv if found, None otherwise
    """
    if not click_hwnd:
        return None

    try:
        hwnd_hex = format(click_hwnd, "08X")
        username = os.environ.get("USERNAME")
        csv_path = Path(f"C:/Users/{username}/AppData/Local/Temp/CLICK ({hwnd_hex})/Address.csv")

        if csv_path.exists():
            return csv_path

        return None

    except Exception as e:
        print(f"Error finding fallback CSV: {e}")
        return None


def get_project_path_from_hwnd(click_hwnd: int | None = None) -> Path | None:
    """Get the project path from a CLICK window handle.

    The project is stored in the Temp folder under CLICK ({hwnd_hex}).

    Args:
        click_hwnd: Window handle of the CLICK software

    Returns:
        Path to the project folder (the CLICK ({hwnd}) parent) or None if not found
    """
    if not click_hwnd:
        return None

    try:
        # Convert window handle to uppercase hex string without '0x' prefix
        hwnd_hex = format(click_hwnd, "08X")

        # Build the expected project path (parent of CLICK folder contains the project)
        username = os.environ.get("USERNAME")
        click_folder = Path(f"C:/Users/{username}/AppData/Local/Temp/CLICK ({hwnd_hex})")

        if click_folder.exists():
            # The project path is the Temp folder containing the CLICK folder
            return click_folder.parent

        return None

    except Exception as e:
        print(f"Error getting project path: {e}")
        return None


def create_access_connection(db_path: str | Path) -> pyodbc.Connection:
    """Create ODBC connection to Access database with driver fallback.

    Tries drivers in order of preference until one succeeds.

    Args:
        db_path: Path to the Access .mdb file

    Returns:
        Active pyodbc Connection

    Raises:
        RuntimeError: If no drivers available or all fail to connect
    """
    available_drivers = get_available_access_drivers()

    if not available_drivers:
        raise RuntimeError("No Microsoft Access ODBC drivers available")

    # Try drivers in order of preference, then any other available
    driver_errors = []
    drivers_to_try = PREFERRED_ACCESS_DRIVERS + [
        d for d in available_drivers if d not in PREFERRED_ACCESS_DRIVERS
    ]

    for driver in drivers_to_try:
        try:
            conn_str = f"DRIVER={{{driver}}};DBQ={db_path};"
            conn = pyodbc.connect(conn_str)
            print(f"Successfully connected using driver: {driver}")
            return conn
        except pyodbc.Error as e:
            driver_errors.append(f"Driver '{driver}' failed: {e}")
            continue

    error_msg = "Failed to connect with any Access driver:\n" + "\n".join(driver_errors)
    raise RuntimeError(error_msg)
