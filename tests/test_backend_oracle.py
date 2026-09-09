"""Oracle tests: the Jet worker must read and write exactly what Access ODBC does.

These need both a Microsoft Access ODBC driver and the 32-bit Windows PowerShell
Jet worker on the same machine, so they are excluded from ``make test`` and CI by
the ``backend`` marker. Run them with ``make test-backend``.

Every write goes through the production ``save_changes`` path of one backend and is
then read back through ``load_all_addresses`` of *both* backends. The two readers
must agree with each other at the ``AddressRow`` level and at the raw stored-column
level, so a normalization difference (for example ``"1"`` versus ``"001"`` in the
Address text column) cannot hide behind a backend's own round trip.
"""

from __future__ import annotations

import shutil
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pyodbc
import pytest
from pyclickplc.addresses import get_addr_key
from pyclickplc.banks import DEFAULT_RETENTIVE, MEMORY_TYPE_TO_DATA_TYPE

from clicknick.models.address_row import AddressRow
from clicknick.utils import jet_sidecar, mdb_operations, mdb_shared

pytestmark = pytest.mark.backend

RAW_SQL = (
    "SELECT [AddrKey],[MemoryType],[Address],[Nickname],[Comment],[Use],[DataType],"
    "[InitialValue],[Retentive] FROM [address] ORDER BY [AddrKey]"
)

LONG_COMMENT = 'Line one\r\n\tO\'Brien said "hello" \\ backslash ' + "text " * 1800


def _odbc_driver() -> str:
    available = mdb_shared.get_available_access_drivers()
    drivers = [d for d in mdb_shared.PREFERRED_ACCESS_DRIVERS if d in available]
    if not drivers:
        pytest.skip("No Microsoft Access ODBC driver is installed")
    return drivers[0]


def _odbc_raw_connect(path: Path) -> pyodbc.Connection:
    return pyodbc.connect(f"DRIVER={{{_odbc_driver()}}};DBQ={path};")


def _open(backend: str, path: Path) -> mdb_operations.MdbConnection:
    """Open the production MdbConnection with an explicitly chosen backend."""
    connection = mdb_operations.MdbConnection(str(path))
    if backend == "odbc":
        connection._conn = _odbc_raw_connect(path)
    else:
        connection._conn = jet_sidecar.JetConnection(path)
    return connection


def _load(backend: str, path: Path) -> dict[int, AddressRow]:
    connection = _open(backend, path)
    try:
        return mdb_operations.load_all_addresses(connection)
    finally:
        connection.close()


def _raw_rows(backend: str, path: Path) -> list[list]:
    """Stored column values exactly as each backend reports them."""
    if backend == "jet":
        return jet_sidecar.JetConnection(path).load_addresses()
    with closing(_odbc_raw_connect(path)) as connection, closing(connection.cursor()) as cursor:
        return [list(row) for row in cursor.execute(RAW_SQL).fetchall()]


def _assert_backends_agree(path: Path) -> dict[int, AddressRow]:
    odbc_rows, jet_rows = _load("odbc", path), _load("jet", path)
    assert odbc_rows == jet_rows
    assert _raw_rows("odbc", path) == _raw_rows("jet", path)
    return odbc_rows


@pytest.fixture
def oracle_db(tmp_path, monkeypatch):
    if not jet_sidecar.is_available():
        pytest.skip("Windows x86 PowerShell is not available")
    _odbc_driver()
    path = tmp_path / "SC_.mdb"
    shutil.copy2(Path(__file__).with_name("SC_.mdb"), path)
    worker = jet_sidecar.JetWorker()
    monkeypatch.setattr(jet_sidecar, "_worker", worker)
    try:
        yield path
    finally:
        worker.close()


def test_pristine_reads_agree(oracle_db):
    rows = _assert_backends_agree(oracle_db)
    assert len(rows) == 408


@pytest.mark.parametrize("writer", ["odbc", "jet"])
def test_writes_are_read_identically_by_both_backends(oracle_db, writer):
    original = _assert_backends_agree(oracle_db)
    ordered = [original[key] for key in sorted(original)]
    first, second, third, doomed = ordered[:4]

    edited = [
        replace(
            first,
            nickname='O\'Brien "quoted" name',
            comment=LONG_COMMENT,
            initial_value="0000123",
            retentive=not first.retentive,
        ),
        replace(second, nickname="Empty comment", comment="", initial_value="0"),
        replace(third, nickname="Café – unicode", comment="éèê"),
    ]
    new_bit = AddressRow(
        memory_type="C",
        address=1999,
        nickname="NEW_BIT",
        comment="inserted by oracle test",
        used=False,
        data_type=MEMORY_TYPE_TO_DATA_TYPE["C"],
        initial_value="",
        retentive=DEFAULT_RETENTIVE.get("C", False),
    )
    new_word = AddressRow(
        memory_type="DS",
        address=4400,
        nickname="NEW_WORD",
        comment="",
        used=False,
        data_type=MEMORY_TYPE_TO_DATA_TYPE["DS"],
        initial_value="-12345",
        retentive=not DEFAULT_RETENTIVE.get("DS", False),
    )
    for row in (new_bit, new_word):
        assert row.addr_key not in original, "fixture already contains the insert target"
    deleted = replace(
        doomed,
        nickname="",
        comment="",
        initial_value="",
        retentive=DEFAULT_RETENTIVE.get(doomed.memory_type, False),
    )
    assert deleted.needs_full_delete(is_dirty=True)

    changes = [*edited, new_bit, new_word, deleted]
    connection = _open(writer, oracle_db)
    try:
        assert mdb_operations.save_changes(connection, changes) == len(changes)
    finally:
        connection.close()

    expected = dict(original)
    for row in (*edited, new_bit, new_word):
        expected[row.addr_key] = row
    del expected[doomed.addr_key]

    after = _assert_backends_agree(oracle_db)
    assert after == expected
    assert get_addr_key("C", 1999) in after
    assert doomed.addr_key not in after


@pytest.mark.parametrize("first_writer,second_writer", [("odbc", "jet"), ("jet", "odbc")])
def test_backends_can_update_each_others_rows(oracle_db, first_writer, second_writer):
    """A row inserted by one backend must be updatable, then deletable, by the other."""
    row = AddressRow(
        memory_type="C",
        address=1998,
        nickname="HANDOFF",
        comment="first",
        used=False,
        data_type=MEMORY_TYPE_TO_DATA_TYPE["C"],
        initial_value="",
        retentive=DEFAULT_RETENTIVE.get("C", False),
    )
    connection = _open(first_writer, oracle_db)
    try:
        assert mdb_operations.save_changes(connection, [row]) == 1
    finally:
        connection.close()
    assert _assert_backends_agree(oracle_db)[row.addr_key] == row

    updated = replace(row, comment="second", retentive=not row.retentive)
    connection = _open(second_writer, oracle_db)
    try:
        assert mdb_operations.save_changes(connection, [updated]) == 1
    finally:
        connection.close()
    assert _assert_backends_agree(oracle_db)[row.addr_key] == updated

    removed = replace(row, nickname="", comment="")
    assert removed.needs_full_delete(is_dirty=True)
    connection = _open(second_writer, oracle_db)
    try:
        assert mdb_operations.save_changes(connection, [removed]) == 1
    finally:
        connection.close()
    assert row.addr_key not in _assert_backends_agree(oracle_db)
