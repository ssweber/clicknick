"""Tests for clicknick.utils.mdb_operations helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from pyclickplc.addresses import get_addr_key
from pyclickplc.banks import DataType

from clicknick.models.address_row import AddressRow
from clicknick.utils import mdb_operations


class _DummyConnection:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        return None


def test_ensure_addresses_exist_inserts_missing_only_and_dedupes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "SC_.mdb"
    db_path.write_bytes(b"")

    existing = {
        get_addr_key("X", 1): AddressRow(memory_type="X", address=1, used=True),
    }
    inserted_rows: list[AddressRow] = []

    monkeypatch.setattr(mdb_operations, "MdbConnection", _DummyConnection)
    monkeypatch.setattr(mdb_operations, "load_all_addresses", lambda _conn: existing)
    monkeypatch.setattr(
        mdb_operations,
        "save_changes",
        lambda _conn, rows: inserted_rows.extend(rows) or len(rows),
    )

    result = mdb_operations.ensure_addresses_exist(str(db_path), ["x1", "X001", "Y001", "y1"])

    assert result["requested_count"] == 2
    assert result["inserted_count"] == 1
    assert result["existing_count"] == 1
    assert result["parsed_addresses"] == ["X001", "Y001"]
    assert len(inserted_rows) == 1
    row = inserted_rows[0]
    assert row.memory_type == "Y"
    assert row.address == 1
    assert row.used is True
    assert row.data_type == DataType.BIT


def test_ensure_addresses_exist_expands_range_endpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "SC_.mdb"
    db_path.write_bytes(b"")
    inserted_rows: list[AddressRow] = []

    monkeypatch.setattr(mdb_operations, "MdbConnection", _DummyConnection)
    monkeypatch.setattr(mdb_operations, "load_all_addresses", lambda _conn: {})
    monkeypatch.setattr(
        mdb_operations,
        "save_changes",
        lambda _conn, rows: inserted_rows.extend(rows) or len(rows),
    )

    result = mdb_operations.ensure_addresses_exist(str(db_path), ["Y001..Y005", "Y005"])

    assert result["requested_count"] == 2
    assert result["inserted_count"] == 2
    assert result["existing_count"] == 0
    assert result["parsed_addresses"] == ["Y001", "Y005"]
    assert {(row.memory_type, row.address) for row in inserted_rows} == {("Y", 1), ("Y", 5)}


def test_ensure_addresses_exist_requires_existing_db_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mdb"
    with pytest.raises(FileNotFoundError, match="MDB file not found"):
        mdb_operations.ensure_addresses_exist(str(missing), ["X001"])


class _FakeCursor:
    """Records each statement and answers the existence check with *exists*."""

    def __init__(self, exists: bool):
        self.exists = exists
        self.writes: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        if not sql.strip().startswith("SELECT"):
            self.writes.append((sql, params))

    def fetchone(self) -> tuple[int]:
        return (1 if self.exists else 0,)


def _stored_initial_value(row: AddressRow, *, exists: bool) -> str:
    cursor = _FakeCursor(exists)
    mdb_operations._upsert_rows(cursor, [row])
    ((sql, params),) = cursor.writes
    assert sql.lstrip().startswith("UPDATE" if exists else "INSERT")
    # UPDATE binds InitialValue third, INSERT seventh.
    return params[2] if exists else params[6]


@pytest.mark.parametrize("exists", [False, True], ids=["insert", "update"])
@pytest.mark.parametrize(
    ("memory_type", "data_type", "initial", "expected"),
    [
        ("DS", DataType.INT, "", "0"),
        ("C", DataType.BIT, "", "0"),
        ("T", DataType.BIT, "", "0"),
        ("DH", DataType.HEX, "", "0"),
        ("XD", DataType.HEX, "", "0"),
        ("TXT", DataType.TXT, "", ""),
        ("DS", DataType.INT, "5", "5"),
        ("DH", DataType.HEX, "00FF", "00FF"),
        ("TXT", DataType.TXT, "A", "A"),
        ("TXT", DataType.TXT, " ", " "),
    ],
)
def test_upsert_writes_the_initial_value_that_click_stores(
    memory_type: str, data_type: int, initial: str, expected: str, exists: bool
) -> None:
    row = AddressRow(
        memory_type=memory_type,
        address=1,
        data_type=data_type,
        nickname="a",
        initial_value=initial,
    )
    assert _stored_initial_value(row, exists=exists) == expected


def test_jet_save_writes_the_initial_value_that_click_stores() -> None:
    captured: list[list] = []

    class _FakeJet(mdb_operations.JetConnection):
        def __init__(self) -> None:
            pass

        def save_addresses(self, deletes, upserts):
            captured.extend(upserts)
            return len(upserts)

    conn = mdb_operations.MdbConnection("unused.mdb")
    conn._conn = _FakeJet()
    rows = [
        AddressRow(memory_type="DS", address=1, data_type=DataType.INT, nickname="a"),
        AddressRow(memory_type="TXT", address=1, data_type=DataType.TXT, nickname="b"),
        AddressRow(
            memory_type="DS", address=2, data_type=DataType.INT, nickname="c", initial_value="7"
        ),
    ]
    mdb_operations.save_changes(conn, rows)

    assert [upsert[6] for upsert in captured] == ["0", "", "7"]
