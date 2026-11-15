"""A nickname or comment is stored as CLICK stores it: without a space at either end.

Loaded rows that hold one are trimmed by a staged edit, "Trim spaces", that Sync
writes and Undo takes back; a value entered with one is stored without it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyclickplc import AUTOMATIONDIRECT_SYSTEM_NICKNAMES
from pyclickplc.addresses import get_addr_key
from pyclickplc.banks import DataType

from clicknick.data.address_store import TRIM_DESCRIPTION, AddressStore
from clicknick.data.data_source import CsvDataSource
from clicknick.models.address_row import AddressRow
from clicknick.services import ImportService
from clicknick.services.block_service import remove_block_tag
from clicknick.widgets.import_csv_dialog import detect_blocks_in_csv

EDGE = "Cannot start or end with a space"
C1, C2, C3 = (get_addr_key("C", n) for n in (1, 2, 3))
DS1 = get_addr_key("DS", 1)
SC1 = get_addr_key("SC", 1)
SD1 = get_addr_key("SD", 1)
X1, X2 = get_addr_key("X", 1), get_addr_key("X", 2)
T1, TD1 = get_addr_key("T", 1), get_addr_key("TD", 1)


class LiveSource:
    """A database CLICK writes too: rows change without the store being told."""

    supports_used_field = True
    file_path = "live.mdb"
    is_read_only = False
    is_database = True

    def __init__(self, rows: dict[int, AddressRow]) -> None:
        self.rows = dict(rows)
        self.saved: list[list[AddressRow]] = []

    def load_all_addresses(self) -> dict[int, AddressRow]:
        return dict(self.rows)

    def save_changes(self, rows) -> int:
        self.saved.append(list(rows))
        for row in rows:
            self.rows[row.addr_key] = AddressRow(
                memory_type=row.memory_type,
                address=row.address,
                nickname=row.nickname,
                comment=row.comment,
                initial_value=row.initial_value,
                retentive=row.retentive,
            )
        return len(rows)


def _store(rows: dict[int, AddressRow]) -> tuple[AddressStore, LiveSource]:
    source = LiveSource(rows)
    store = AddressStore(source)
    store.load_initial_data()
    return store, source


def _pump() -> dict[int, AddressRow]:
    return {
        C1: AddressRow("C", 1, nickname="Pump ", comment=" Main pump"),
        C2: AddressRow("C", 2, nickname="Fan"),
    }


class TestTrimOnLoad:
    def test_load_stages_the_trim_as_one_undo_step_that_sync_writes(self):
        store, source = _store(_pump())

        row = store.visible_state[C1]
        assert (row.nickname, row.comment) == ("Pump", "Main pump")
        assert not row.has_reportable_error
        assert store.get_dirty_keys() == {C1}
        assert store.base_state[C1].nickname == "Pump "
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

        assert store.save_all_changes() == {C1}
        written = source.saved[0]
        assert [(row.nickname, row.comment) for row in written] == [("Pump", "Main pump")]
        assert not store.has_unsaved_changes()

    def test_undo_puts_the_spaces_back_and_they_show_the_error(self):
        store, _source = _store(_pump())

        assert store.undo()

        row = store.visible_state[C1]
        assert (row.nickname, row.comment) == ("Pump ", " Main pump")
        assert (row.nickname_error, row.comment_error) == (EDGE, EDGE)
        assert not store.has_unsaved_changes()
        assert store.redo()
        assert store.visible_state[C1].nickname == "Pump"

    def test_a_reload_does_not_trim_again_what_the_user_undid(self):
        store, source = _store(_pump())
        store.undo()

        source.rows[C3] = AddressRow("C", 3, nickname="Motor")
        assert store._on_database_update()

        assert store.visible_state[C1].nickname == "Pump "
        assert store.undo_stack == []
        assert not store.has_unsaved_changes()

    def test_a_reload_trims_again_a_row_the_database_changed(self):
        store, source = _store(_pump())
        store.undo()

        source.rows[C1] = AddressRow("C", 1, nickname="Pump ", comment="Main pump")
        assert store._on_database_update()

        assert store.visible_state[C1].nickname == "Pump"
        assert store.get_dirty_keys() == {C1}
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

    def test_a_reload_that_brings_edge_spaces_stages_them_as_one_step(self):
        store, source = _store({C2: AddressRow("C", 2, nickname="Fan")})
        assert store.undo_stack == []

        source.rows[C1] = AddressRow("C", 1, nickname="Pump ")
        source.rows[C3] = AddressRow("C", 3, comment="Spare ")
        assert store._on_database_update()

        assert store.visible_state[C1].nickname == "Pump"
        assert store.visible_state[C3].comment == "Spare"
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

    def test_a_reload_without_edge_spaces_pushes_no_undo_step(self):
        store, source = _store({C2: AddressRow("C", 2, nickname="Fan")})
        with store.edit_session("Rename") as session:
            session.set_field(C2, "nickname", "Blower")

        source.rows[C3] = AddressRow("C", 3, nickname="Motor")
        assert store._on_database_update()

        assert [frame.description for frame in store.undo_stack] == ["Rename"]

    def test_a_field_the_user_edits_is_not_trimmed_over(self):
        store, source = _store({C2: AddressRow("C", 2, nickname="Fan")})
        with store.edit_session("Rename") as session:
            session.set_field(C1, "nickname", "Blower")

        source.rows[C1] = AddressRow("C", 1, nickname="Pump ", comment="Main ")
        assert store._on_database_update()

        row = store.visible_state[C1]
        assert (row.nickname, row.comment) == ("Blower", "Main")
        assert store.user_overrides[C1] == {"nickname": "Blower", "comment": "Main"}

    def test_a_sync_that_reads_new_edge_spaces_first_writes_them_trimmed(self):
        store, source = _store({C2: AddressRow("C", 2, nickname="Fan")})
        with store.edit_session("Rename") as session:
            session.set_field(C2, "nickname", "Blower")
        # CLICK writes between two polls; Sync reads the database first.
        source.rows[C1] = AddressRow("C", 1, nickname="Pump ")

        assert store.save_all_changes() == {C1, C2}

        assert source.rows[C1].nickname == "Pump"
        assert source.rows[C2].nickname == "Blower"
        assert store.undo_stack == []

    def test_no_system_name_of_clicks_has_an_edge_space(self):
        """So trimming every loaded nickname never touches one of CLICK's own names."""
        names = [
            name
            for guidance in AUTOMATIONDIRECT_SYSTEM_NICKNAMES.values()
            for name in (guidance.nickname, *guidance.repair_from)
        ]

        assert names
        assert [name for name in names if name != name.strip(" ")] == []

    def test_a_system_name_of_clicks_is_left_as_it_is(self):
        store, _source = _store({SC1: AddressRow("SC", 1, nickname="_Always_ON", comment="On ")})

        assert store.visible_state[SC1].nickname == "_Always_ON"
        assert store.visible_state[SC1].comment == "On"
        assert store.user_overrides[SC1] == {"comment": "On"}

    @pytest.mark.parametrize(
        ("memory_type", "address", "nickname"),
        [
            ("X", 3, "_IO1_Module_Error "),  # generated by CLICK, exempt as loaded
            ("SC", 1, "log "),  # a reserved word, exempt on SC
            ("X", 4, "Bad-Name "),  # breaks the user rules, exempt as loaded like any X name
        ],
    )
    def test_a_name_exempt_as_loaded_stays_exempt_once_trimmed(
        self, memory_type, address, nickname
    ):
        key = get_addr_key(memory_type, address)
        store, source = _store({key: AddressRow(memory_type, address, nickname=nickname)})

        row = store.visible_state[key]
        assert row.nickname == nickname.strip(" ")
        assert row.loaded_with_error
        assert not row.has_reportable_error
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

        assert store.save_all_changes() == {key}
        assert source.rows[key].nickname == nickname.strip(" ")

    def test_a_name_typed_over_a_loaded_one_is_not_exempt(self):
        key = get_addr_key("X", 3)
        store, _source = _store({key: AddressRow("X", 3, nickname="_IO1_Module_Error ")})
        with store.edit_session("Rename") as session:
            session.set_field(key, "nickname", "_IO1_Module_Err")

        assert not store.visible_state[key].loaded_with_error
        assert store.visible_state[key].has_reportable_error

    def test_x_and_sd_nicknames_flagged_as_loaded_are_trimmed_too(self):
        store, source = _store(
            {
                X1: AddressRow("X", 1, nickname="Stop "),
                X2: AddressRow("X", 2, nickname=" Start PB"),
                SD1: AddressRow("SD", 1, nickname="My_Code ", data_type=DataType.INT),
            }
        )

        assert store.base_state[X1].loaded_with_error
        assert [store.visible_state[key].nickname for key in (X1, X2, SD1)] == [
            "Stop",
            "Start PB",
            "My_Code",
        ]
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

        assert store.save_all_changes() == {X1, X2, SD1}
        assert [source.rows[key].nickname for key in (X1, X2, SD1)] == [
            "Stop",
            "Start PB",
            "My_Code",
        ]

    def test_a_trim_that_makes_two_nicknames_the_same_shows_the_duplicate(self):
        store, _source = _store(
            {C1: AddressRow("C", 1, nickname="Pump"), C2: AddressRow("C", 2, nickname="Pump ")}
        )

        assert store.visible_state[C2].nickname == "Pump"
        assert store.visible_state[C1].nickname_error == "Duplicate"
        assert store.visible_state[C2].nickname_error == "Duplicate"
        with pytest.raises(RuntimeError, match="validation errors"):
            store.save_all_changes()

    def test_a_csv_load_stages_the_trim(self, tmp_path: Path):
        path = tmp_path / "Nicknames.csv"
        path.write_bytes(b'Address,Nickname,Address Comment\r\nDS1,"Speed "," Setpoint"\r\n')
        store = AddressStore(CsvDataSource(str(path)))
        store.load_initial_data()

        row = store.visible_state[DS1]
        assert (row.nickname, row.comment) == ("Speed", "Setpoint")
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

        store.save_all_changes()
        assert b'DS1,INT,"Speed",0,Yes,"Setpoint"' in path.read_bytes()

    def test_a_trim_read_while_a_session_is_open_is_staged_when_it_ends(self):
        store, source = _store({C2: AddressRow("C", 2, nickname="Fan")})
        source.rows[C1] = AddressRow("C", 1, nickname="Pump ")

        with store.edit_session("Rename") as session:
            session.set_field(C2, "nickname", "Blower")
            assert store._on_database_update()
            assert store.visible_state[C1].nickname == "Pump "

        assert store.visible_state[C1].nickname == "Pump"
        assert [frame.description for frame in store.undo_stack] == ["Rename", TRIM_DESCRIPTION]

    def test_a_trim_whose_session_raised_is_staged_by_the_next_reading(self):
        store, source = _store({C2: AddressRow("C", 2, nickname="Fan")})
        source.rows[C1] = AddressRow("C", 1, nickname="Pump ")

        with pytest.raises(RuntimeError), store.edit_session("Rename"):
            assert store._on_database_update()
            raise RuntimeError("edit failed")
        assert store.visible_state[C1].nickname == "Pump "

        source.rows[C3] = AddressRow("C", 3, nickname="Motor")
        assert store._on_database_update()

        assert store.visible_state[C1].nickname == "Pump"
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

    def test_discard_goes_back_to_the_rows_as_loaded_trims_included(self):
        store, _source = _store(_pump())
        with store.edit_session("Rename") as session:
            session.set_field(C2, "nickname", "Blower")

        store.discard_all_changes()

        assert store.visible_state[C2].nickname == "Fan"
        assert store.visible_state[C1].nickname == "Pump"
        assert store.get_dirty_keys() == {C1}
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

    def test_a_load_without_edge_spaces_has_nothing_to_undo(self):
        store, _source = _store({C2: AddressRow("C", 2, nickname="Fan", comment="Blower")})

        assert store.undo_stack == []
        assert not store.has_unsaved_changes()


class TestTrimOnEntry:
    @pytest.mark.parametrize(
        ("field", "value", "stored"),
        [
            ("nickname", "Pump ", "Pump"),
            ("nickname", "  Pump", "Pump"),
            ("comment", " Main pump ", "Main pump"),
            ("comment", "Two  spaces inside", "Two  spaces inside"),
        ],
    )
    def test_a_value_is_stored_without_its_edge_spaces(self, field, value, stored):
        store, _source = _store({})
        with store.edit_session("Edit") as session:
            session.set_field(C1, field, value)

        row = store.visible_state[C1]
        assert getattr(row, field) == stored
        assert not row.has_reportable_error

    def test_entering_the_loaded_value_with_a_space_changes_nothing(self):
        store, _source = _store({C1: AddressRow("C", 1, nickname="Pump")})
        with store.edit_session("Edit") as session:
            session.set_field(C1, "nickname", "Pump ")

        assert not store.has_unsaved_changes()
        assert store.undo_stack == []

    @pytest.mark.parametrize("comment", ["<Tm_D />  preset", "preset  <Tm_D />"])
    def test_a_pair_cascade_that_leaves_a_space_is_trimmed(self, comment):
        # Removing the block from T1 removes its tag on TD1 too; the second of
        # two spaces beside the tag would be left at an end of TD1's comment.
        store, _source = _store(
            {T1: AddressRow("T", 1, comment="<Tm />"), TD1: AddressRow("TD", 1, comment=comment)}
        )
        with store.edit_session("Remove block") as session:
            session.set_field(T1, "comment", "")

        assert store.visible_state[TD1].comment == "preset"
        assert not store.has_errors()

    @pytest.mark.parametrize("comment", ["<Motor>  Main pump", "Main pump  <Motor>"])
    def test_removing_a_close_tag_trims_the_open_row_it_cascades_to(self, comment):
        store, _source = _store(
            {C1: AddressRow("C", 1, comment=comment), C3: AddressRow("C", 3, comment="</Motor>")}
        )
        with store.edit_session("Edit") as session:
            session.set_field(C3, "comment", "")

        assert store.visible_state[C1].comment == "Main pump"
        assert not store.has_errors()

    @pytest.mark.parametrize("comment", ["<Motor>  Main pump", "Main pump  <Motor>"])
    def test_remove_block_trims_what_the_tag_leaves(self, comment):
        store, _source = _store(
            {C1: AddressRow("C", 1, comment=comment), C3: AddressRow("C", 3, comment="</Motor>")}
        )
        # As the Address Editor's Remove Block does
        with store.edit_session("Remove block tag") as session:
            session.set_field(C1, "comment", remove_block_tag(comment))

        assert store.visible_state[C1].comment == "Main pump"
        assert store.visible_state[C3].comment == ""
        assert not store.has_errors()

    def test_an_import_in_block_tag_mode_trims_the_comment_it_composes(self):
        store, _source = _store(
            {
                C1: AddressRow("C", 1, comment="<Old> Motor note"),
                C3: AddressRow("C", 3, comment="</Old>"),
            }
        )
        csv_rows = [AddressRow("C", 1, comment="<New>"), AddressRow("C", 3, comment="</New>")]
        blocks = detect_blocks_in_csv(csv_rows)
        options = {id(block): {"comment": "Block Tag"} for block in blocks}

        with store.edit_session("Import") as session:
            ImportService.merge_blocks(store, session, blocks, options)

        assert store.visible_state[C1].comment == "Motor note <New>"
        assert store.visible_state[C3].comment == "</New>"
        assert not store.has_errors()
