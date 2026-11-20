"""A nickname, a comment and a non-Text initial value are stored as CLICK stores them.

CLICK stores a nickname and a non-Text initial value without a space or a tab at either end.
A loaded row that has one is trimmed by a staged edit, "Trim spaces". Sync writes that edit
and Undo takes it back. A value that is entered with a space or a tab is stored without it.
A Text initial value keeps its edges.

CLICK 4.00 stores a comment that you type in its Address Picker with the spaces at its ends.
ClickNick keeps the spaces and tabs at the ends of a comment, wherever the comment comes from,
and they are not an error. ClickNick trims nothing from a comment. A line break or another
control code at either end is kept, and it is an error.
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
from clicknick.models.validation import CONTROL_EDGE_ERROR, EDGE_CHARACTERS
from clicknick.services import ImportService
from clicknick.services.block_service import add_block_tag, remove_block_tag
from clicknick.utils import mdb_operations
from clicknick.widgets.import_csv_dialog import detect_blocks_in_csv

EDGE = "Cannot start or end with a space"
C1, C2, C3 = (get_addr_key("C", n) for n in (1, 2, 3))
DS1 = get_addr_key("DS", 1)
SC1 = get_addr_key("SC", 1)
SD1 = get_addr_key("SD", 1)
X1, X2 = get_addr_key("X", 1), get_addr_key("X", 2)
T1, TD1 = get_addr_key("T", 1), get_addr_key("TD", 1)


class LiveSource:
    """A database that CLICK writes to as well. Its rows change without the store being told."""

    supports_used_field = True
    stored_row = staticmethod(mdb_operations.stored_row)
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
        assert (row.nickname, row.comment) == ("Pump", " Main pump")
        assert not row.has_reportable_error
        assert store.get_dirty_keys() == {C1}
        assert store.user_overrides[C1] == {"nickname": "Pump"}
        assert store.base_state[C1].nickname == "Pump "
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

        assert store.save_all_changes() == {C1}
        written = source.saved[0]
        assert [(row.nickname, row.comment) for row in written] == [("Pump", " Main pump")]
        assert not store.has_unsaved_changes()

    def test_undo_puts_the_spaces_back_and_they_show_the_error(self):
        store, _source = _store(_pump())

        assert store.undo()

        row = store.visible_state[C1]
        assert (row.nickname, row.comment) == ("Pump ", " Main pump")
        assert (row.nickname_error, row.comment_error) == (EDGE, "")
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
        source.rows[C2] = AddressRow("C", 2, nickname="Fan ")
        source.rows[C3] = AddressRow("C", 3, comment="Spare ")
        assert store._on_database_update()

        assert store.visible_state[C1].nickname == "Pump"
        assert store.visible_state[C2].nickname == "Fan"
        assert store.visible_state[C3].comment == "Spare "
        assert store.get_dirty_keys() == {C1, C2}
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

        source.rows[C1] = AddressRow("C", 1, nickname="Pump ", initial_value=" 1", comment="Main ")
        assert store._on_database_update()

        row = store.visible_state[C1]
        assert (row.nickname, row.initial_value, row.comment) == ("Blower", "1", "Main ")
        assert store.user_overrides[C1] == {"nickname": "Blower", "initial_value": "1"}

    def test_a_sync_that_reads_new_edge_spaces_first_writes_them_trimmed(self):
        store, source = _store({C2: AddressRow("C", 2, nickname="Fan")})
        with store.edit_session("Rename") as session:
            session.set_field(C2, "nickname", "Blower")
        # CLICK writes between two polls. Sync reads the database before it writes.
        source.rows[C1] = AddressRow("C", 1, nickname="Pump ")

        assert store.save_all_changes() == {C1, C2}

        assert source.rows[C1].nickname == "Pump"
        assert source.rows[C2].nickname == "Blower"
        assert store.undo_stack == []

    def test_no_system_name_of_clicks_has_an_edge_space_or_tab(self):
        """No system name of CLICK's has a space or a tab at either end.

        Trimming every loaded nickname therefore never changes one of CLICK's own names.
        """
        names = [
            name
            for guidance in AUTOMATIONDIRECT_SYSTEM_NICKNAMES.values()
            for name in (guidance.nickname, *guidance.repair_from)
        ]

        assert names
        assert [name for name in names if name != name.strip(EDGE_CHARACTERS)] == []

    def test_a_system_name_of_clicks_is_left_as_it_is(self):
        # The row's initial value is trimmed, and the trim leaves the nickname alone.
        store, _source = _store(
            {SC1: AddressRow("SC", 1, nickname="_Always_ON", initial_value="1 ")}
        )

        assert store.visible_state[SC1].nickname == "_Always_ON"
        assert store.visible_state[SC1].initial_value == "1"
        assert store.user_overrides[SC1] == {"initial_value": "1"}

    # A nickname that CLICK holds on X, SC or SD and that breaks ClickNick's nickname rules
    # is "exempt as loaded". The store flags it loaded_with_error and reports no error for it.
    @pytest.mark.parametrize(
        ("memory_type", "address", "nickname"),
        [
            ("X", 3, "_IO1_Module_Error "),  # CLICK generates this name
            ("SC", 1, "log "),  # a reserved word, which CLICK writes on SC
            ("X", 4, "Bad-Name "),  # breaks the user rules, and is exempt like any loaded X name
        ],
    )
    def test_a_name_exempt_as_loaded_keeps_its_format_exemption_once_trimmed(
        self, memory_type, address, nickname
    ):
        key = get_addr_key(memory_type, address)
        store, source = _store({key: AddressRow(memory_type, address, nickname=nickname)})

        assert store.base_state[key].loaded_with_error
        row = store.visible_state[key]
        assert row.nickname == nickname.strip(" ")
        assert not row.loaded_with_error  # the trimmed name differs from the name as loaded
        assert row.nickname_valid
        assert not row.has_reportable_error
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

        assert store.save_all_changes() == {key}
        assert source.rows[key].nickname == nickname.strip(" ")

    @pytest.mark.parametrize(
        ("memory_type", "first", "second"),
        [("X", "Stop ", " Stop"), ("SC", "log ", "log")],
    )
    def test_a_trimmed_name_exempt_as_loaded_is_checked_for_duplicates(
        self, memory_type, first, second
    ):
        one, two = get_addr_key(memory_type, 1), get_addr_key(memory_type, 2)
        store, source = _store(
            {
                one: AddressRow(memory_type, 1, nickname=first),
                two: AddressRow(memory_type, 2, nickname=second),
            }
        )

        assert store.visible_state[one].nickname_error == "Duplicate"
        assert store.visible_state[one].has_reportable_error
        assert store.has_errors()
        with pytest.raises(RuntimeError, match="validation errors"):
            store.save_all_changes()
        assert source.rows[one].nickname == first

    def test_names_shown_as_loaded_are_exempt_duplicates_included(self):
        """A name shown exactly as loaded, untrimmed, stays exempt from the duplicate check.

        CLICK's data may repeat a system name that CLICK wrote.
        """
        one, two = get_addr_key("SC", 1), get_addr_key("SC", 2)
        store, _source = _store(
            {one: AddressRow("SC", 1, nickname="log"), two: AddressRow("SC", 2, nickname="LOG")}
        )

        assert store.visible_state[one].loaded_with_error
        assert store.visible_state[two].loaded_with_error
        assert not store.has_errors()
        assert store.undo_stack == []

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
        assert (row.nickname, row.comment) == ("Speed", " Setpoint")
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

        store.save_all_changes()
        assert b'DS1,INT,"Speed",0,Yes," Setpoint"' in path.read_bytes()

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

    @pytest.mark.parametrize("comment", [" a\n", "\r\n a ", "Note\x01", "a \n\t"])
    def test_a_loaded_comment_with_a_line_break_at_an_end_stays_as_it_is(self, comment):
        # ClickNick trims nothing from a comment. The line break or control code is an error.
        store, _source = _store({C1: AddressRow("C", 1, comment=comment)})

        row = store.visible_state[C1]
        assert row.comment == comment
        assert row.comment_error == CONTROL_EDGE_ERROR
        assert store.undo_stack == []
        assert not store.has_unsaved_changes()

    def test_a_load_without_edge_spaces_has_nothing_to_undo(self):
        store, _source = _store({C2: AddressRow("C", 2, nickname="Fan", comment="Blower")})

        assert store.undo_stack == []
        assert not store.has_unsaved_changes()


class TestTrimOnEntry:
    @pytest.mark.parametrize(("value", "stored"), [("Pump ", "Pump"), ("  Pump", "Pump")])
    def test_a_nickname_is_stored_without_its_edge_spaces(self, value, stored):
        store, _source = _store({})
        with store.edit_session("Edit") as session:
            session.set_field(C1, "nickname", value)

        row = store.visible_state[C1]
        assert row.nickname == stored
        assert not row.has_reportable_error

    @pytest.mark.parametrize("comment", [" Note2 ", " Main pump", "Two  spaces inside ", "\tTab\t"])
    def test_a_comment_is_stored_with_its_edge_spaces(self, comment):
        store, _source = _store({})
        with store.edit_session("Edit") as session:
            session.set_field(C1, "comment", comment)

        row = store.visible_state[C1]
        assert row.comment == comment
        assert not row.has_reportable_error

    def test_a_comment_typed_with_a_line_break_at_its_end_keeps_it_and_shows_the_error(self):
        store, _source = _store({})
        with store.edit_session("Edit") as session:
            session.set_field(C1, "comment", " Note2\n")

        row = store.visible_state[C1]
        assert row.comment == " Note2\n"
        assert row.comment_error == CONTROL_EDGE_ERROR

    def test_entering_the_loaded_value_with_a_space_changes_nothing(self):
        store, _source = _store({C1: AddressRow("C", 1, nickname="Pump")})
        with store.edit_session("Edit") as session:
            session.set_field(C1, "nickname", "Pump ")

        assert not store.has_unsaved_changes()
        assert store.undo_stack == []

    def test_adding_a_space_to_a_loaded_comment_is_an_edit(self):
        store, source = _store({C1: AddressRow("C", 1, comment="Note2")})
        with store.edit_session("Edit") as session:
            session.set_field(C1, "comment", " Note2 ")

        assert store.get_dirty_keys() == {C1}
        assert [frame.description for frame in store.undo_stack] == ["Edit"]
        assert store.save_all_changes() == {C1}
        assert source.rows[C1].comment == " Note2 "

    @pytest.mark.parametrize(
        ("comment", "left"),
        [
            ("<Tm_D /> preset", "preset"),
            ("preset <Tm_D />", "preset"),
            ("<Tm_D />  preset", " preset"),
            ("preset  <Tm_D />", "preset "),
            ("preset\t<Tm_D />", "preset\t"),
            ("<Tm_D />\npreset", "preset"),
            ("preset\r\n<Tm_D />", "preset"),
        ],
    )
    def test_a_pair_cascade_removes_the_tag_and_one_separator(self, comment, left):
        # Removing the block from T1 removes its tag on TD1 too. The tag takes the one space,
        # or else the one line break, that separates it from the text. A second separator or
        # a tab belongs to the comment.
        store, _source = _store(
            {T1: AddressRow("T", 1, comment="<Tm />"), TD1: AddressRow("TD", 1, comment=comment)}
        )
        with store.edit_session("Remove block") as session:
            session.set_field(T1, "comment", "")

        assert store.visible_state[TD1].comment == left
        assert not store.has_errors()

    @pytest.mark.parametrize("comment", ["preset ", " preset", "  ", "preset", ""])
    def test_a_pair_cascade_that_adds_and_removes_a_tag_gives_the_comment_back(self, comment):
        store, source = _store(
            {T1: AddressRow("T", 1, comment="delay"), TD1: AddressRow("TD", 1, comment=comment)}
        )
        with store.edit_session("Add block") as session:
            session.set_field(T1, "comment", add_block_tag("delay", "<Tm />"))
        assert store.visible_state[TD1].comment == add_block_tag(comment, "<Tm_D />")

        with store.edit_session("Remove block") as session:
            session.set_field(T1, "comment", remove_block_tag(store.visible_state[T1].comment))

        assert store.visible_state[T1].comment == "delay"
        assert store.visible_state[TD1].comment == comment
        assert store.get_dirty_keys() == set()
        assert source.rows[TD1].comment == comment

    @pytest.mark.parametrize(
        ("comment", "left"),
        [
            ("<Motor> Main pump", "Main pump"),
            ("<Motor>  Main pump", " Main pump"),
            ("Main pump  <Motor>", "Main pump "),
            ("<Motor> Main pump ", "Main pump "),
            ("<Motor>\nMain pump", "Main pump"),
        ],
    )
    def test_removing_a_close_tag_removes_the_open_tag_and_one_separator(self, comment, left):
        store, _source = _store(
            {C1: AddressRow("C", 1, comment=comment), C3: AddressRow("C", 3, comment="</Motor>")}
        )
        with store.edit_session("Edit") as session:
            session.set_field(C3, "comment", "")

        assert store.visible_state[C1].comment == left
        assert not store.has_errors()

    @pytest.mark.parametrize(
        ("comment", "left"),
        [
            ("<Motor> Main pump", "Main pump"),
            ("<Motor>  Main pump", " Main pump"),
            (" Main pump <Motor>", " Main pump"),
        ],
    )
    def test_remove_block_removes_the_tag_and_one_space(self, comment, left):
        store, _source = _store(
            {C1: AddressRow("C", 1, comment=comment), C3: AddressRow("C", 3, comment="</Motor>")}
        )
        # Remove the tag the way the Address Editor's Remove Block does.
        with store.edit_session("Remove block tag") as session:
            session.set_field(C1, "comment", remove_block_tag(comment))

        assert store.visible_state[C1].comment == left
        assert store.visible_state[C3].comment == ""
        assert not store.has_errors()

    @pytest.mark.parametrize(
        ("comment", "composed"),
        [("<Old> Motor note", "Motor note <New>"), (" Note2 <Old>", " Note2 <New>")],
    )
    def test_an_import_in_block_tag_mode_replaces_the_tag_and_its_space(self, comment, composed):
        store, _source = _store(
            {
                C1: AddressRow("C", 1, comment=comment),
                C3: AddressRow("C", 3, comment="</Old>"),
            }
        )
        csv_rows = [AddressRow("C", 1, comment="<New>"), AddressRow("C", 3, comment="</New>")]
        blocks = detect_blocks_in_csv(csv_rows)
        options = {id(block): {"comment": "Block Tag"} for block in blocks}

        with store.edit_session("Import") as session:
            ImportService.merge_blocks(store, session, blocks, options)

        assert store.visible_state[C1].comment == composed
        assert store.visible_state[C3].comment == "</New>"
        assert not store.has_errors()


# A space or a tab at the start or the end of a value, and the value that CLICK stores
EDGES = [" 5", "5 ", "\t5", "5\t"]
# The fields that lose their edge spaces and tabs, on DS1 (an INT)
DS_FIELDS = ["nickname", "initial_value"]
TXT1 = get_addr_key("TXT", 1)


def _edged(field: str, edge: str) -> str:
    """Return *edge* as a value of *field*. A nickname cannot be a bare number."""
    return edge.replace("5", "Pump5") if field != "initial_value" else edge


def _ds_row(field: str, value: str) -> AddressRow:
    return AddressRow("DS", 1, data_type=DataType.INT, retentive=False, **{field: value})


class TestEdgeTabsAndInitialValues:
    """A nickname and an initial value of any type but Text lose a space or a tab at either
    end. A Text initial value keeps them, because CLICK keeps them in a quoted one. A comment
    keeps them too.
    """

    @pytest.mark.parametrize("edge", EDGES)
    @pytest.mark.parametrize("field", DS_FIELDS)
    def test_an_entered_value_is_stored_without_the_edge(self, field, edge):
        store, _source = _store({})
        with store.edit_session("Edit") as session:
            session.set_field(DS1, field, _edged(field, edge))

        row = store.visible_state[DS1]
        assert getattr(row, field) == _edged(field, "5")
        assert not row.has_reportable_error

    @pytest.mark.parametrize("edge", EDGES)
    @pytest.mark.parametrize("field", DS_FIELDS)
    def test_a_loaded_value_is_trimmed_by_the_staged_edit(self, field, edge):
        store, source = _store({DS1: _ds_row(field, _edged(field, edge))})

        row = store.visible_state[DS1]
        assert getattr(row, field) == _edged(field, "5")
        assert not row.has_reportable_error
        assert [frame.description for frame in store.undo_stack] == [TRIM_DESCRIPTION]

        assert store.save_all_changes() == {DS1}
        assert getattr(source.rows[DS1], field) == _edged(field, "5")

    @pytest.mark.parametrize("edge", EDGES)
    def test_a_loaded_comment_keeps_its_edge_through_an_edit_and_a_sync(self, edge):
        comment = _edged("comment", edge)
        store, source = _store({DS1: _ds_row("comment", comment)})

        row = store.visible_state[DS1]
        assert row.comment == comment
        assert not row.has_reportable_error
        assert store.undo_stack == []
        assert not store.has_unsaved_changes()

        with store.edit_session("Rename") as session:
            session.set_field(DS1, "nickname", "Speed")
        assert store.visible_state[DS1].comment == comment
        assert store.user_overrides[DS1] == {"nickname": "Speed"}

        assert store.save_all_changes() == {DS1}
        assert [row.comment for row in source.saved[0]] == [comment]
        assert source.rows[DS1].comment == comment
        assert store.visible_state[DS1].comment == comment
        assert not store.has_unsaved_changes()

    @pytest.mark.parametrize("value", [" ", "\t"])
    def test_a_text_initial_value_keeps_its_space_or_tab(self, value):
        store, _source = _store(
            {TXT1: AddressRow("TXT", 1, data_type=DataType.TXT, initial_value=value)}
        )
        with store.edit_session("Edit") as session:
            session.set_field(TXT1, "initial_value", value)

        assert store.visible_state[TXT1].initial_value == value
        assert store.undo_stack == []
        assert not store.has_errors()

    @pytest.mark.parametrize("edge", EDGES)
    def test_a_csv_load_trims_each_field_but_the_comment(self, tmp_path: Path, edge):
        """File > Load Nicknames from CSV. pyclickplc's reader strips the initial value."""
        cells = [_edged(field, edge) for field in ("nickname", "initial_value", "comment")]
        path = tmp_path / "Nicknames.csv"
        path.write_bytes(
            b"Address,Data Type,Nickname,Initial Value,Retentive,Address Comment\r\n"
            + 'DS1,INT,"{}","{}",No,"{}"\r\n'.format(*cells).encode()
        )
        store = AddressStore(CsvDataSource(str(path)))
        store.load_initial_data()

        row = store.visible_state[DS1]
        assert (row.nickname, row.initial_value, row.comment) == ("Pump5", "5", cells[2])
        assert not row.has_reportable_error

        store.save_all_changes()
        assert f'DS1,INT,"Pump5",5,No,"{cells[2]}"'.encode() in path.read_bytes()

    @pytest.mark.parametrize("edge", EDGES)
    def test_an_import_from_csv_trims_each_field_but_the_comment(self, tmp_path: Path, edge):
        """The Address Editor's File > Import from CSV, with every field overwritten."""
        cells = [_edged(field, edge) for field in ("nickname", "initial_value", "comment")]
        path = tmp_path / "Import.csv"
        path.write_bytes(
            b"Address,Data Type,Nickname,Initial Value,Retentive,Address Comment\r\n"
            + 'DS1,INT,"{}","{}",No,"{}"\r\n'.format(*cells).encode()
        )
        csv_rows = list(CsvDataSource(str(path)).load_all_addresses().values())
        blocks = detect_blocks_in_csv(csv_rows)
        overwrite = {"nickname": "Overwrite", "comment": "Overwrite", "first_scan": "Overwrite"}
        store, _source = _store({})

        with store.edit_session("Import from CSV") as session:
            ImportService.merge_blocks(
                store, session, blocks, {id(block): overwrite for block in blocks}
            )

        row = store.visible_state[DS1]
        assert (row.nickname, row.initial_value, row.comment) == ("Pump5", "5", cells[2])
        assert not row.has_reportable_error
