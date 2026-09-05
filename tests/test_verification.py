"""Regression tests for the legacy MDB/CDV verification action."""

from types import SimpleNamespace

from clicknick.models.address_row import AddressRow
from clicknick.utils.verification import verify_mdb_addresses


def _verify_row(row: AddressRow) -> list[str]:
    shared_data = SimpleNamespace(all_rows={row.addr_key: row})
    return verify_mdb_addresses(shared_data)


def test_verify_accepts_ordinary_x_nickname() -> None:
    row = AddressRow(memory_type="X", address=1, nickname="StartButton")

    assert _verify_row(row) == []


def test_verify_accepts_loaded_x_system_nickname() -> None:
    row = AddressRow(memory_type="X", address=1, nickname="_IO1_Module_Error")

    assert _verify_row(row) == []


def test_verify_still_rejects_non_io_leading_underscore_on_x() -> None:
    row = AddressRow(memory_type="X", address=1, nickname="_StartButton")

    issues = _verify_row(row)

    assert len(issues) == 1
    assert "X1 nickname invalid" in issues[0]
    assert "Cannot start with _" in issues[0]
