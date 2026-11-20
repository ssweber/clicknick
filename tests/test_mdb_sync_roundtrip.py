"""A Sync into SC_.mdb or a nickname CSV, followed by a reload, changes nothing in the store."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.data.data_source import CsvDataSource, MdbDataSource
from clicknick.utils import mdb_shared

# Rows that the Address Editor can create and that SC_.mdb has no content for: TD, DS, DH and C
# store '0', and TXT stores ''.
NEW_ROWS = (("TD", 401), ("DS", 4001), ("DH", 401), ("C", 1901), ("TXT", 901))
KEYS = [get_addr_key(memory_type, address) for memory_type, address in NEW_ROWS]


@pytest.fixture
def temp_mdb(tmp_path: Path) -> str:
    available = mdb_shared.get_available_access_drivers()
    if not any(driver in available for driver in mdb_shared.PREFERRED_ACCESS_DRIVERS):
        pytest.skip("No Microsoft Access ODBC driver is installed")
    path = tmp_path / "SC_.mdb"
    shutil.copy2(Path(__file__).with_name("SC_.mdb"), path)
    return str(path)


def _set_all(store: AddressStore, step: str, **fields: str) -> None:
    with store.edit_session(step) as session:
        for key, (memory_type, address) in zip(KEYS, NEW_ROWS, strict=True):
            for name, value in fields.items():
                if name == "nickname" and value:
                    value = f"{memory_type}_row{address}"
                session.set_field(key, name, value)


def _sync_then_reload(store: AddressStore, step: str) -> None:
    assert store.save_all_changes() == set(KEYS), step
    after_sync = dict(store.visible_state)
    notified: list[set[int]] = []
    store.add_observer(lambda _store, keys: notified.append(set(keys)))

    store._on_database_update()

    assert notified == [], step
    assert store.visible_state == after_sync, step
    assert not store.has_unsaved_changes(), step
    assert not store.undo_stack, step


@pytest.mark.parametrize("kind", ["mdb", "csv"])
def test_insert_update_and_delete_then_reload_change_nothing(
    kind: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    if kind == "mdb":
        source = MdbDataSource(db_path=request.getfixturevalue("temp_mdb"))
    else:
        csv_path = tmp_path / "nicknames.csv"
        csv_path.write_bytes(b"")
        source = CsvDataSource(str(csv_path), required=())
    store = AddressStore(source)
    store.load_initial_data()

    _set_all(store, "insert", nickname="x")
    _sync_then_reload(store, "insert")
    for key, (memory_type, _) in zip(KEYS, NEW_ROWS, strict=True):
        # The source holds '0', and the store shows what the source holds.
        assert store.visible_state[key].initial_value == ("" if memory_type == "TXT" else "0")

    _set_all(store, "update", comment="a comment")
    _sync_then_reload(store, "update")

    _set_all(store, "delete", nickname="", comment="")
    _sync_then_reload(store, "delete")
