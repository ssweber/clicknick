"""Tests for CSV import block detection and merge behavior."""

from __future__ import annotations

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.models.address_row import AddressRow
from clicknick.services import ImportService
from clicknick.widgets.import_csv_dialog import detect_blocks_in_csv


def mk(addr: int, nickname: str = "", comment: str = "") -> AddressRow:
    return AddressRow(memory_type="C", address=addr, nickname=nickname, comment=comment)


@pytest.fixture
def csv_rows() -> list[AddressRow]:
    """CSV rows where a tagged block sits between untagged rows."""
    return [
        mk(1, "FREE_A"),
        mk(2, "FREE_B"),
        mk(3, "MOTOR_1", "<Motor>"),
        mk(4, "MOTOR_2"),
        mk(5, "MOTOR_3", "</Motor>"),
        mk(6, "FREE_C"),
    ]


class MockDataSource:
    """Mock data source - the store builds an empty skeleton from it."""

    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def load_all_addresses(self):
        return {}

    def save_changes(self, rows):
        return len(rows)


@pytest.fixture
def store() -> AddressStore:
    """Store with empty skeleton rows."""
    s = AddressStore(MockDataSource())
    s.load_initial_data()
    return s


def nicknames_of(block_name: str, rows: list[AddressRow]) -> list[str]:
    blocks = detect_blocks_in_csv(rows)
    block = next(b for b in blocks if b.name == block_name)
    return [r.nickname for r in block.rows]


class TestDetectBlocks:
    def test_untagged_excludes_rows_of_a_tagged_block_between_them(self, csv_rows):
        # Untagged rows are not contiguous - the Motor block sits between them.
        # Untagged must not swallow the Motor rows.
        assert nicknames_of("Untagged", csv_rows) == ["FREE_A", "FREE_B", "FREE_C"]

    def test_tagged_block_holds_exactly_its_own_rows(self, csv_rows):
        assert nicknames_of("Motor", csv_rows) == ["MOTOR_1", "MOTOR_2", "MOTOR_3"]

    def test_every_row_belongs_to_exactly_one_block(self, csv_rows):
        blocks = detect_blocks_in_csv(csv_rows)
        seen = [r.nickname for b in blocks for r in b.rows]
        assert sorted(seen) == sorted(r.nickname for r in csv_rows)


class TestMergeBlocks:
    def test_unchecked_block_is_not_imported(self, store, csv_rows):
        """Deselecting a block in the dialog must leave its addresses untouched."""
        blocks = detect_blocks_in_csv(csv_rows)
        # User unchecks "Motor", leaving only "Untagged" selected
        selected = [b for b in blocks if b.name != "Motor"]
        options = {id(b): {"nickname": "Overwrite"} for b in selected}

        with store.edit_session("Import") as session:
            ImportService.merge_blocks(store, session, selected, options)

        assert store.get_visible_row(get_addr_key("C", 1)).nickname == "FREE_A"
        assert store.get_visible_row(get_addr_key("C", 6)).nickname == "FREE_C"
        # Motor addresses were deselected - they must remain empty
        for addr in (3, 4, 5):
            assert store.get_visible_row(get_addr_key("C", addr)).nickname == ""

    def test_per_block_options_are_applied_independently(self, store, csv_rows):
        """Each block uses its own merge mode, even for the same field."""
        blocks = detect_blocks_in_csv(csv_rows)
        options = {}
        for b in blocks:
            # Import nicknames for Motor only; skip them for Untagged
            mode = "Overwrite" if b.name == "Motor" else "Skip"
            options[id(b)] = {"nickname": mode}

        with store.edit_session("Import") as session:
            ImportService.merge_blocks(store, session, blocks, options)

        assert store.get_visible_row(get_addr_key("C", 3)).nickname == "MOTOR_1"
        assert store.get_visible_row(get_addr_key("C", 1)).nickname == ""

    def test_merge_mode_does_not_overwrite_existing_value(self, store, csv_rows):
        blocks = detect_blocks_in_csv(csv_rows)
        with store.edit_session("Preexisting") as session:
            session.set_field(get_addr_key("C", 1), "nickname", "KEEP_ME")

        options = {id(b): {"nickname": "Merge"} for b in blocks}
        with store.edit_session("Import") as session:
            ImportService.merge_blocks(store, session, blocks, options)

        assert store.get_visible_row(get_addr_key("C", 1)).nickname == "KEEP_ME"
        assert store.get_visible_row(get_addr_key("C", 2)).nickname == "FREE_B"

    def test_skip_mode_changes_nothing(self, store, csv_rows):
        blocks = detect_blocks_in_csv(csv_rows)
        options = {
            id(b): {"nickname": "Skip", "comment": "Skip", "first_scan": "Skip"} for b in blocks
        }

        with store.edit_session("Import") as session:
            ImportService.merge_blocks(store, session, blocks, options)

        assert not store.get_dirty_keys()


class TestImportDoesNotFakeChanges:
    def test_importing_values_that_already_match_marks_nothing_changed(self, store, csv_rows):
        """Importing a CSV that already matches the project must leave no dirty rows.

        Overwrite writes every field unconditionally, so without the store dropping
        no-op overrides every imported row would show under the "Changed" filter
        with no cell diff, and would be rewritten to the database on save.
        """
        blocks = detect_blocks_in_csv(csv_rows)
        options = {id(b): {"nickname": "Overwrite", "comment": "Overwrite"} for b in blocks}

        # First import: the project is empty, so everything is a genuine change
        with store.edit_session("Import") as session:
            ImportService.merge_blocks(store, session, blocks, options)
        assert store.get_dirty_keys()

        store.save_all_changes()  # imported values are now the base state

        # Re-importing the same CSV changes nothing
        with store.edit_session("Re-import") as session:
            ImportService.merge_blocks(store, session, blocks, options)

        assert not store.get_dirty_keys()


class TestFirstScan:
    """Initial value and retentive are one decision: what the address holds on first scan.

    A retentive address powers up with its retained value, so its initial value never
    applies. Importing one field without the other would silently change first-scan
    behavior, so they are always written as a pair.
    """

    def rows_with(self, initial_value: str, retentive: bool) -> list[AddressRow]:
        return [
            AddressRow(
                memory_type="C",
                address=1,
                nickname="MOTOR",
                initial_value=initial_value,
                retentive=retentive,
            )
        ]

    def import_first_scan(self, store, rows, mode: str) -> None:
        blocks = detect_blocks_in_csv(rows)
        options = {id(b): {"first_scan": mode} for b in blocks}
        with store.edit_session("Import") as session:
            ImportService.merge_blocks(store, session, blocks, options)

    def test_overwrite_takes_both_fields_from_csv(self, store):
        self.import_first_scan(store, self.rows_with("5", retentive=True), "Overwrite")

        row = store.get_visible_row(get_addr_key("C", 1))
        assert row.initial_value == "5"
        assert row.retentive is True

    def test_merge_does_not_shadow_an_existing_initial_value(self, store):
        """The reported hazard: importing retentive=True onto an address whose
        initial value the program relies on would make CLICK ignore that value."""
        addr_key = get_addr_key("C", 1)
        with store.edit_session("Existing setup") as session:
            session.set_field(addr_key, "initial_value", "42")

        # CSV wants this address retentive. Under Merge, first-scan behavior is
        # already deliberate here, so the pair must be left alone entirely.
        self.import_first_scan(store, self.rows_with("", retentive=True), "Merge")

        row = store.get_visible_row(addr_key)
        assert row.initial_value == "42"
        assert row.retentive is False

    def test_merge_does_not_shadow_an_existing_retentive_flag(self, store):
        addr_key = get_addr_key("C", 1)
        with store.edit_session("Existing setup") as session:
            session.set_field(addr_key, "retentive", True)

        self.import_first_scan(store, self.rows_with("7", retentive=False), "Merge")

        row = store.get_visible_row(addr_key)
        assert row.retentive is True
        assert row.initial_value == ""

    def test_merge_claims_addresses_still_at_defaults(self, store):
        self.import_first_scan(store, self.rows_with("9", retentive=True), "Merge")

        row = store.get_visible_row(get_addr_key("C", 1))
        assert row.initial_value == "9"
        assert row.retentive is True

    def test_skip_leaves_both_fields_alone(self, store):
        self.import_first_scan(store, self.rows_with("9", retentive=True), "Skip")

        row = store.get_visible_row(get_addr_key("C", 1))
        assert row.initial_value == ""
        assert row.retentive is False
