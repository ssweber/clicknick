"""A folder's nicknames.csv is staged in the store as edits, never written to CLICK directly."""

from __future__ import annotations

from pathlib import Path

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.data.data_source import CsvDataSource
from clicknick.models.address_row import AddressRow
from clicknick.services.nickname_staging import plan_nicknames, stage_nicknames

X1, X2, X3 = (get_addr_key("X", n) for n in (1, 2, 3))


class _Database:
    supports_used_field = True
    is_database = True
    is_read_only = False
    file_path = "SC_.mdb"

    def __init__(self, rows: dict[int, AddressRow]) -> None:
        self._rows = rows
        self.saved: list[AddressRow] = []

    def load_all_addresses(self) -> dict[int, AddressRow]:
        return self._rows

    def save_changes(self, rows: list[AddressRow]) -> int:
        self.saved.extend(rows)
        return len(rows)


@pytest.fixture
def store() -> AddressStore:
    """CLICK's database: X001 is Start, X002 is Stop, X003 has no nickname."""
    store = AddressStore(
        _Database(
            {
                X1: AddressRow("X", 1, nickname="Start", comment="Green button"),
                X2: AddressRow("X", 2, nickname="Stop"),
            }
        )
    )
    store.load_initial_data()
    return store


def _rows(**by_address: tuple[str, str]) -> dict[int, AddressRow]:
    """Rows of a nicknames.csv: ``X3=("Jog", "")`` gives X003 nickname Jog, no comment."""
    out = {}
    for address, (nickname, comment) in by_address.items():
        memory_type, number = address[0], int(address[1:])
        out[get_addr_key(memory_type, number)] = AddressRow(
            memory_type, number, nickname=nickname, comment=comment
        )
    return out


def test_plan_counts_new_renamed_cleared_and_other(store: AddressStore) -> None:
    rows = _rows(X1=("Start", "Push to run"), X2=("", ""), X3=("Jog", ""), C1=("Running", ""))
    rows[X2] = AddressRow("X", 2)  # listed with no nickname: cleared

    plan = plan_nicknames(rows, store.visible_state)

    assert (plan.added, plan.renamed, plan.cleared, plan.other) == (2, 0, 1, 1)
    assert plan.summary() == "2 new, 1 cleared, 1 other"
    assert [(c.display_address, c.field, c.new) for c in plan.changes] == [
        ("X001", "comment", "Push to run"),
        ("X002", "nickname", ""),
        ("X003", "nickname", "Jog"),
        ("C1", "nickname", "Running"),
    ]


def test_plan_leaves_addresses_the_file_does_not_list(store: AddressStore) -> None:
    plan = plan_nicknames(_rows(X3=("Jog", "")), store.visible_state)

    assert {change.addr_key for change in plan.changes} == {X3}
    assert plan_nicknames(_rows(X1=("Start", "Green button")), store.visible_state).changes == ()


def test_a_default_initial_value_spelled_zero_is_not_a_change(store: AddressStore) -> None:
    key = get_addr_key("DS", 1)
    rows = {key: AddressRow("DS", 1, initial_value="0", retentive=True)}

    assert not plan_nicknames(rows, store.visible_state)


def test_staging_is_one_undoable_edit_and_sync_puts_it_in_the_database(
    store: AddressStore,
) -> None:
    rows = _rows(X1=("Start_PB", "Green button"), X3=("Jog", ""))
    plan = plan_nicknames(rows, store.visible_state)

    assert stage_nicknames(store, plan, "Nicknames from bundle") == 2

    assert store.visible_state[X1].nickname == "Start_PB"
    assert store.visible_state[X3].nickname == "Jog"
    assert store.base_state[X1].nickname == "Start"  # Not in CLICK until Sync
    assert not plan_nicknames(rows, store.visible_state)
    assert plan_nicknames(rows, store.base_state).summary() == "1 new, 1 renamed"

    store.undo()
    assert store.visible_state[X1].nickname == "Start"
    store.redo()

    store.save_all_changes()
    assert not plan_nicknames(rows, store.base_state)


def test_an_empty_plan_stages_nothing(store: AddressStore) -> None:
    assert stage_nicknames(store, plan_nicknames({}, store.visible_state), "nothing") == 0
    assert not store.undo_stack


def test_rows_read_from_a_nicknames_csv(tmp_path: Path, store: AddressStore) -> None:
    path = tmp_path / "nicknames.csv"
    CsvDataSource(str(path)).save_changes(
        [
            AddressRow("X", 3, nickname="Jog"),
            AddressRow("X", 1, nickname="Start", comment="Green button"),
        ]
    )

    plan = plan_nicknames(CsvDataSource(str(path)).load_all_addresses(), store.visible_state)

    assert plan.summary() == "1 new"


def test_only_the_columns_the_file_has_are_staged(tmp_path: Path) -> None:
    ds1 = get_addr_key("DS", 1)
    store = AddressStore(
        _Database(
            {
                X1: AddressRow("X", 1, nickname="Start", comment="Green button"),
                ds1: AddressRow("DS", 1, nickname="Speed", data_type=1, initial_value="1500"),
            }
        )
    )
    store.load_initial_data()
    path = tmp_path / "nicknames.csv"
    path.write_text("Address,Nickname\r\nX001,Start_PB\r\nDS1,Speed\r\n", encoding="utf-8")
    source = CsvDataSource(str(path))
    rows = source.load_all_addresses()

    plan = plan_nicknames(rows, store.visible_state, fields=source.fields)

    assert [(c.display_address, c.field, c.new) for c in plan.changes] == [
        ("X001", "nickname", "Start_PB")
    ]
    stage_nicknames(store, plan, "Nicknames from bundle")
    assert store.visible_state[X1].comment == "Green button"
    assert store.visible_state[ds1].initial_value == "1500"
    assert not plan_nicknames(rows, store.visible_state, fields=source.fields)


def test_a_file_without_a_retentive_column_leaves_retentive_alone() -> None:
    store = AddressStore(_Database({X1: AddressRow("X", 1, nickname="Start", retentive=True)}))
    store.load_initial_data()
    rows = {X1: AddressRow("X", 1, nickname="Start", comment="Green button")}

    plan = plan_nicknames(rows, store.visible_state, fields={"nickname", "comment"})

    assert [(c.field, c.new) for c in plan.changes] == [("comment", "Green button")]
