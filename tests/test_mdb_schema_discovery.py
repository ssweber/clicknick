"""Test to discover SC_.mdb schema and data for Initial Value and Retentive features.

Schema:
- AddrKey: Number (primary key)
- MemoryType: Long Text (X, Y, C, DS, etc.)
- Address: Long Text (address number)
- DataType: Number (determines value type: bit, int, int2, float, hex, txt)
- Nickname: Long Text
- Use: Yes/No
- InitialValue: Long Text (stored as string)
- Retentive: Yes/No
- Comment: Long Text

Discovered DataType mapping:
- 0 = bit (C, CT, SC, T, X, Y) - values: "0" or "1"
- 1 = int 16-bit (DS, SD, TD) - values: "-32768" to "32767"
- 2 = int2 32-bit (CTD, DD) - values: "-2147483648" to "2147483647"
- 3 = float (DF) - values: "-3.4028235E+38" to "3.4028235E+38"
- 4 = hex (DH, XD, YD) - values: "0000" to "FFFF"
- 6 = txt (TXT) - values: single ASCII character

Retentive/InitialValue Edit Rules for Address Editor:
- EDITABLE: X, Y, C, T, CT, DS, DD, DF, DH, TXT
- NOT EDITABLE (system types): SC, SD, XD, YD
- NOT EDITABLE (stored elsewhere by CLICK): CTD, TD
"""

import shutil
import tempfile
from pathlib import Path

import pyodbc
import pytest


def get_mdb_connection(mdb_path: Path):
    """Create a database connection to the MDB file."""
    drivers = [
        "Microsoft Access Driver (*.mdb, *.accdb)",
        "Microsoft Access Driver (*.mdb)",
    ]

    for driver in drivers:
        try:
            conn_str = f"DRIVER={{{driver}}};DBQ={mdb_path};"
            return pyodbc.connect(conn_str)
        except pyodbc.Error:
            continue

    return None


@pytest.fixture
def temp_mdb():
    """Create a temporary copy of SC_.mdb for testing."""
    src = Path(__file__).parent / "SC_.mdb"
    if not src.exists():
        pytest.skip("SC_.mdb not found in tests folder")

    # Create temp copy
    with tempfile.NamedTemporaryFile(suffix=".mdb", delete=False) as tmp:
        temp_path = Path(tmp.name)

    shutil.copy2(src, temp_path)
    yield temp_path
    # Cleanup
    temp_path.unlink(missing_ok=True)


class TestMdbDiscovery:
    """Consolidated discovery tests - each test uses its own connection to avoid Access ODBC issues."""

    def test_datatype_mapping(self, temp_mdb):
        """Show DataType values for each memory type."""
        conn = get_mdb_connection(temp_mdb)
        if not conn:
            pytest.skip("No Microsoft Access ODBC driver available")

        try:
            cursor = conn.cursor()

            print("\n" + "=" * 60)
            print("DATATYPE VALUES BY MEMORY TYPE:")
            print("=" * 60)

            cursor.execute("""
                SELECT MemoryType, DataType, COUNT(*) as cnt
                FROM address
                GROUP BY MemoryType, DataType
                ORDER BY MemoryType, DataType
            """)

            current_type = None
            for row in cursor.fetchall():
                mem_type, data_type, count = row
                if mem_type != current_type:
                    print(f"\n  {mem_type}:")
                    current_type = mem_type
                print(f"    DataType={data_type} ({count} rows)")

            cursor.close()
        finally:
            conn.close()

    def test_retentive_by_memory_type(self, temp_mdb):
        """Show Retentive settings grouped by memory type."""
        conn = get_mdb_connection(temp_mdb)
        if not conn:
            pytest.skip("No Microsoft Access ODBC driver available")

        try:
            cursor = conn.cursor()

            print("\n" + "=" * 60)
            print("RETENTIVE BY MEMORY TYPE:")
            print("=" * 60)
            print("(True=Retentive, False=Non-Retentive)")

            cursor.execute("""
                SELECT MemoryType, Retentive, COUNT(*) as cnt
                FROM address
                GROUP BY MemoryType, Retentive
                ORDER BY MemoryType, Retentive
            """)

            current_type = None
            for row in cursor.fetchall():
                mem_type, retentive, count = row
                if mem_type != current_type:
                    print(f"\n  {mem_type}:")
                    current_type = mem_type
                ret_str = "Retentive" if retentive else "Non-Retentive"
                print(f"    {ret_str}: {count} rows")

            cursor.close()
        finally:
            conn.close()

    def test_initial_value_range_by_datatype(self, temp_mdb):
        """Show InitialValue ranges grouped by DataType (to understand validation)."""
        conn = get_mdb_connection(temp_mdb)
        if not conn:
            pytest.skip("No Microsoft Access ODBC driver available")

        try:
            cursor = conn.cursor()

            print("\n" + "=" * 60)
            print("INITIAL VALUE RANGES BY DATATYPE:")
            print("=" * 60)
            print("(Helps determine validation rules per data type)")

            cursor.execute("""
                SELECT DISTINCT DataType
                FROM address
                ORDER BY DataType
            """)
            data_types = [row[0] for row in cursor.fetchall()]

            for dt in data_types:
                # Get sample initial values for this data type
                cursor.execute(
                    """
                    SELECT MemoryType, Address, InitialValue
                    FROM address
                    WHERE DataType = ? AND InitialValue IS NOT NULL AND InitialValue <> ''
                    ORDER BY MemoryType, Address
                """,
                    (dt,),
                )
                rows = cursor.fetchmany(5)

                if rows:
                    print(f"\n  DataType={dt}:")
                    for row in rows:
                        print(f"    {row[0]}{row[1]}: InitialValue='{row[2]}'")

                    # Try to find min/max as numbers if possible
                    cursor.execute(
                        """
                        SELECT InitialValue
                        FROM address
                        WHERE DataType = ? AND InitialValue IS NOT NULL AND InitialValue <> ''
                    """,
                        (dt,),
                    )
                    all_values = [row[0] for row in cursor.fetchall()]

                    # Try numeric conversion
                    numeric_values = []
                    for v in all_values:
                        try:
                            numeric_values.append(float(v))
                        except (ValueError, TypeError):
                            pass

                    if numeric_values:
                        print(
                            f"    Numeric range: min={min(numeric_values)}, max={max(numeric_values)}"
                        )
                else:
                    print(f"\n  DataType={dt}: (no InitialValue examples)")

            cursor.close()
        finally:
            conn.close()

    def test_sample_rows_all_columns(self, temp_mdb):
        """Show sample rows with all columns for reference."""
        conn = get_mdb_connection(temp_mdb)
        if not conn:
            pytest.skip("No Microsoft Access ODBC driver available")

        try:
            cursor = conn.cursor()

            print("\n" + "=" * 60)
            print("SAMPLE ROWS (ALL COLUMNS):")
            print("=" * 60)

            # Get a few rows with interesting data (non-empty InitialValue)
            cursor.execute("""
                SELECT AddrKey, MemoryType, Address, DataType, Nickname, Use, InitialValue, Retentive, Comment
                FROM address
                WHERE InitialValue IS NOT NULL AND InitialValue <> ''
                ORDER BY MemoryType, Address
            """)

            rows = cursor.fetchmany(20)
            if rows:
                print("\nRows with InitialValue:")
                for row in rows:
                    print(
                        f"  {row[1]}{row[2]}: DataType={row[3]}, Init='{row[6]}', Ret={row[7]}, Nick='{row[4] or ''}', Use={row[5]}"
                    )

            cursor.close()
        finally:
            conn.close()

    def test_all_rows_dump(self, temp_mdb):
        """Dump ALL rows for complete analysis."""
        conn = get_mdb_connection(temp_mdb)
        if not conn:
            pytest.skip("No Microsoft Access ODBC driver available")

        try:
            cursor = conn.cursor()

            print("\n" + "=" * 60)
            print("ALL ROWS IN DATABASE:")
            print("=" * 60)

            cursor.execute("""
                SELECT MemoryType, Address, DataType, Nickname, InitialValue, Retentive, Use, Comment
                FROM address
                ORDER BY MemoryType, Address
            """)

            current_type = None
            for row in cursor.fetchall():
                mem_type, addr, dt, nick, init_val, ret, use, comment = row
                if mem_type != current_type:
                    print(f"\n--- {mem_type} (DataType={dt}) ---")
                    current_type = mem_type
                ret_str = "R" if ret else "-"
                use_str = "U" if use else "-"
                init_str = f"Init='{init_val}'" if init_val else ""
                nick_str = f"'{nick}'" if nick else "(no name)"
                print(f"  {mem_type}{addr}: {nick_str} [{ret_str}{use_str}] {init_str}")

            cursor.close()
        finally:
            conn.close()



# Note: TestExternalMdbChanges class removed - external DB change detection
# is now handled by AddressStore._on_database_update() with base/overlay architecture.
# See test_address_store.py for tests of the new architecture.
