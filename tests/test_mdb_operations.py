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
