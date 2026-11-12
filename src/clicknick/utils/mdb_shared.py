"""Shared MDB/Access database utilities.

Provides common functions for locating and connecting to Access databases
used by both NicknameManager and the Address Editor.
"""

from __future__ import annotations

import os
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pyodbc

from ..utils.win32_utils import WIN32
from .click_temp import click_temp_dir
from .jet_sidecar import JetConnection
from .jet_sidecar import is_available as jet_is_available

PREFERRED_ACCESS_DRIVERS = [
    "Microsoft Access Driver (*.mdb, *.accdb)",
    "Microsoft Access Driver (*.mdb)",
    "Microsoft Access Driver",
]


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
    return len(get_available_access_drivers()) > 0


def get_database_backend() -> str:
    """Return the requested backend; the environment also reaches child workers."""
    backend = os.environ.get("CLICKNICK_DB_BACKEND", "auto").strip().lower()
    if backend not in {"auto", "odbc", "jet", "none"}:
        raise ValueError("CLICKNICK_DB_BACKEND must be auto, odbc, jet, or none.")
    return backend


def uses_jet_backend() -> bool:
    """Determine whether connection startup should prepare the Jet worker."""
    backend = get_database_backend()
    return backend == "jet" or (backend == "auto" and not has_access_driver())


def has_database_backend() -> bool:
    """Check candidates for the selected backend; creation tests the actual MDB."""
    backend = get_database_backend()
    if backend == "none":
        return False
    if backend == "jet":
        return jet_is_available()
    if backend == "odbc":
        return has_access_driver()
    return has_access_driver() or jet_is_available()


@dataclass(frozen=True)
class ConnectionTestResult:
    success: bool
    message: str


def create_access_connection(db_path: str | Path) -> pyodbc.Connection | JetConnection:
    """Prefer native ODBC, using x86 Windows Jet when its driver is unavailable.

    Tries drivers in order of preference until one succeeds.

    Args:
        db_path: Path to the Access .mdb file

    Returns:
        Active native ODBC or Windows Jet connection

    Raises:
        RuntimeError: If no backend can connect
    """
    backend = get_database_backend()
    if backend == "none":
        raise RuntimeError("Database access is disabled (CSV mode).")
    if not Path(db_path).is_file():
        raise FileNotFoundError(f"MDB file not found: {db_path}")
    if backend == "jet":
        return JetConnection(db_path)
    available_drivers = get_available_access_drivers()

    if not available_drivers:
        if backend == "odbc":
            raise RuntimeError("No Microsoft Access ODBC driver available; ODBC was requested.")
        return JetConnection(db_path)

    # Try drivers in order of preference, then any other available
    driver_errors = []
    drivers_to_try = [d for d in PREFERRED_ACCESS_DRIVERS if d in available_drivers] + [
        d for d in available_drivers if d not in PREFERRED_ACCESS_DRIVERS
    ]

    driver_unavailable = True
    for driver in drivers_to_try:
        try:
            conn_str = f"DRIVER={{{driver}}};DBQ={db_path};"
            conn = pyodbc.connect(conn_str)
            print(f"Successfully connected using driver: {driver}")
            return conn
        except pyodbc.Error as e:
            driver_errors.append(f"Driver '{driver}' failed: {e}")
            # Never treat file permissions, locks or corrupt databases as missing drivers.
            if not e.args or e.args[0] not in {"IM002", "IM003", "IM014"}:
                driver_unavailable = False
            continue

    if driver_unavailable and backend == "auto":
        return JetConnection(db_path)
    error_msg = "Failed to connect with any Access driver:\n" + "\n".join(driver_errors)
    raise RuntimeError(error_msg)


def probe_database_connection(db_path: str | Path | None) -> ConnectionTestResult:
    """Read the expected address columns without changing project data."""
    if get_database_backend() == "none":
        return ConnectionTestResult(False, "Database access is disabled (CSV mode).")
    if not db_path:
        return ConnectionTestResult(False, "Open a CLICK project or choose its MDB file first.")
    try:
        with closing(create_access_connection(db_path)) as connection:
            if isinstance(connection, JetConnection):
                backend = connection.backend_name  # Constructor runs the read-only probe.
            else:
                with closing(connection.cursor()) as cursor:
                    cursor.execute(
                        "SELECT TOP 1 [AddrKey], [MemoryType], [Address], [Nickname], [Comment], "
                        "[Use], [DataType], [InitialValue], [Retentive] FROM [address]"
                    ).fetchone()
                backend = "Microsoft Access ODBC"
        return ConnectionTestResult(
            True, f"Connection succeeded: {backend}. Address table is readable."
        )
    except Exception as exc:
        return ConnectionTestResult(False, f"Connection failed: {exc}")


def find_click_database(click_pid: int | None = None, click_hwnd: int | None = None) -> str | None:
    """Find the SC_.mdb of a CLICK window, in its ``CLICK (hwnd)`` temp folder.

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
            db_path = click_temp_dir(click_hwnd) / "SC_.mdb"
            if db_path.exists():
                print(f"Found database: {db_path}")
                return str(db_path)

        return None

    except Exception as e:
        print(f"Error finding database: {e}")
        return None


def find_fallback_csv(click_hwnd: int | None = None) -> Path | None:
    """Find Address.csv in the CLICK temp folder when no database backend connects.

    The CLICK software generates Address.csv in the same folder as SC_.mdb
    when a project is loaded.

    Args:
        click_hwnd: Window handle of the CLICK software

    Returns:
        Path to Address.csv if found, None otherwise
    """
    if not click_hwnd:
        return None
    csv_path = click_temp_dir(click_hwnd) / "Address.csv"
    return csv_path if csv_path.exists() else None
