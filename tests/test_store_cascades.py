"""Block tag cascades in AddressStore edit sessions.

A cascade changes rows the caller did not set: the matching open/close tag of a
renamed block, the T/TD (CT/CTD) pair's block tag, and the pair's Retentive.
What the caller set is never overwritten, a pair or match changes only when the
edited row's block tag changed, and a renamed tag is replaced in place.
"""

from __future__ import annotations

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.models.address_row import AddressRow
from clicknick.views.address_editor.view_builder import build_unified_view


class Source:
    supports_used_field = True
    file_path = "cascades.mdb"
    is_read_only = False
    is_database = True

    def __init__(self, rows):
        self.rows = rows

    def load_all_addresses(self):
        return dict(self.rows)

    def save_changes(self, rows):
        for row in rows:
            self.rows[row.addr_key] = row
        return len(rows)


def key(memory_type: str, address: int) -> int:
    return get_addr_key(memory_type, address)


def make_store(comments: dict[tuple[str, int], str], *, with_view: bool = True) -> AddressStore:
    rows = {
        key(mem, addr): AddressRow(memory_type=mem, address=addr, comment=comment)
        for (mem, addr), comment in comments.items()
    }
    store = AddressStore(Source(rows))
    store.load_initial_data()
    if with_view:
        store.set_unified_view(build_unified_view(store.visible_state))
    return store


def comment(store: AddressStore, mem: str, addr: int) -> str:
    return store.visible_state[key(mem, addr)].comment


def edit(store: AddressStore, *changes: tuple[str, int, str, object]) -> None:
    with store.edit_session("edit") as session:
        for mem, addr, field, value in changes:
            session.set_field(key(mem, addr), field, value)


class TestFreeTextEditsLeaveThePairAlone:
    """store#2: editing only a comment's text never touches the pair's block tag."""

    def test_editing_td_text_keeps_the_t_block(self):
        store = make_store(
            {("T", 1): "<Timers> Fill delay", ("TD", 1): "Fill preset", ("T", 5): "</Timers>"}
        )

        edit(store, ("TD", 1, "comment", "Fill preset (ms)"))

        assert comment(store, "T", 1) == "<Timers> Fill delay"
        assert comment(store, "T", 5) == "</Timers>"
        assert store.get_dirty_keys() == {key("TD", 1)}

    def test_editing_t_text_keeps_the_td_block(self):
        store = make_store({("T", 1): "Fill delay", ("TD", 1): "<Presets_D>"})

        edit(store, ("T", 1, "comment", "Fill delay (s)"))

        assert comment(store, "TD", 1) == "<Presets_D>"
        assert store.get_dirty_keys() == {key("T", 1)}

    def test_editing_text_around_an_unchanged_tag_keeps_the_pair(self):
        store = make_store({("CT", 2): "<Counts />", ("CTD", 2): "<Other_D /> preset"})

        edit(store, ("CT", 2, "comment", "<Counts /> parts made"))

        assert comment(store, "CTD", 2) == "<Other_D /> preset"


class TestRenameInPlace:
    """store#3: a renamed tag is replaced where it is; the rest stays byte for byte."""

    @pytest.mark.parametrize(
        ("close_comment", "renamed"),
        [
            ("</Pumps> end text", "</Tanks> end text"),
            ("</Pumps>  two spaces", "</Tanks>  two spaces"),
            ("Area 1 </Pumps>", "Area 1 </Tanks>"),
            ("before </Pumps> after", "before </Tanks> after"),
        ],
    )
    def test_open_rename_renames_the_close_tag_in_place(self, close_comment, renamed):
        store = make_store({("C", 1): "<Pumps>", ("C", 5): close_comment})

        edit(store, ("C", 1, "comment", "<Tanks>"))
        assert comment(store, "C", 5) == renamed

        edit(store, ("C", 1, "comment", "<Pumps>"))
        assert comment(store, "C", 5) == close_comment
        assert not store.has_unsaved_changes()

    def test_close_rename_keeps_the_open_tag_text_and_colour(self):
        store = make_store({("C", 1): 'Main pumps <Pumps bg="Red">', ("C", 5): "</Pumps>"})

        edit(store, ("C", 5, "comment", "</Tanks>"))

        assert comment(store, "C", 1) == 'Main pumps <Tanks bg="Red">'

    def test_pair_rename_keeps_the_pair_text_where_it_is(self):
        store = make_store({("T", 1): "<Pumps />", ("TD", 1): "<Pumps_D /> preset"})

        edit(store, ("T", 1, "comment", "<Tanks />"))

        assert comment(store, "TD", 1) == "<Tanks_D /> preset"

    def test_every_path_renames_the_same_way(self):
        store = make_store(
            {
                ("T", 1): "<Pumps> start",
                ("TD", 1): "preset <Pumps_D>",
                ("T", 5): "end </Pumps>",
                ("TD", 5): "</Pumps_D>  last",
            }
        )

        edit(store, ("T", 1, "comment", "<Tanks> start"))

        assert comment(store, "TD", 1) == "preset <Tanks_D>"
        assert comment(store, "T", 5) == "end </Tanks>"
        assert comment(store, "TD", 5) == "</Tanks_D>  last"

    def test_colour_change_reaches_the_pair_but_not_the_close_tag(self):
        store = make_store(
            {
                ("T", 1): "<Pumps bg='Red'>",
                ("TD", 1): "note <Pumps_D bg='Red'>",
                ("T", 3): "</Pumps>",
            }
        )

        edit(store, ("T", 1, "comment", "<Pumps bg='Blue'>"))

        assert comment(store, "TD", 1) == 'note <Pumps_D bg="Blue">'
        assert comment(store, "T", 3) == "</Pumps>"

    def test_deleting_the_open_tag_removes_the_close_tag_and_its_separator(self):
        store = make_store(
            {
                ("T", 1): "<Timers> Fill delay",
                ("TD", 1): "Fill preset <Timers_D>",
                ("T", 4): "</Timers> last",
                ("TD", 4): "</Timers_D>",
            }
        )

        edit(store, ("T", 1, "comment", "Fill delay"))

        assert comment(store, "TD", 1) == "Fill preset"
        assert comment(store, "T", 4) == "last"
        assert comment(store, "TD", 4) == ""

    def test_the_match_is_found_without_the_editor_open(self):
        store = make_store({("C", 1): "<Pumps>", ("C", 5): "</Pumps>"}, with_view=False)

        edit(store, ("C", 1, "comment", "<Tanks>"))

        assert comment(store, "C", 5) == "</Tanks>"


class TestTheCallersEditsWin:
    """store#4: a cascade never overwrites a field the caller set in the same session."""

    def test_replacing_both_tags_keeps_both_replacements(self):
        store = make_store({("C", 1): "<Pumps> Pumps area", ("C", 5): "</Pumps>"})

        edit(
            store,
            ("C", 1, "comment", "<Tanks> Tanks area"),
            ("C", 5, "comment", "</Tanks>"),
        )

        assert comment(store, "C", 1) == "<Tanks> Tanks area"
        assert comment(store, "C", 5) == "</Tanks>"

    def test_pasting_a_new_colour_with_its_close_row_keeps_the_colour(self):
        store = make_store({("C", 1): '<Pumps bg="Red">', ("C", 5): "</Pumps>"})

        edit(
            store,
            ("C", 1, "comment", '<Tanks bg="Blue">'),
            ("C", 5, "comment", "</Tanks>"),
        )

        assert comment(store, "C", 1) == '<Tanks bg="Blue">'

    def test_setting_both_rows_of_a_pair_keeps_both(self):
        store = make_store({("T", 1): "<Pumps>", ("TD", 1): "<Pumps_D>"})

        edit(
            store,
            ("T", 1, "comment", "<Tanks>"),
            ("TD", 1, "comment", "typed by hand"),
            ("TD", 1, "retentive", False),
            ("T", 1, "retentive", True),
        )

        assert comment(store, "TD", 1) == "typed by hand"
        assert store.visible_state[key("TD", 1)].retentive is False
        assert store.visible_state[key("T", 1)].retentive is True


class TestCascadeCreatedRowsStillSync:
    """store#5: a row a cascade wrote is not treated as one the caller edited."""

    def test_discard_row_changes_puts_the_pair_and_match_back(self):
        store = make_store(
            {
                ("T", 1): "<Pumps>",
                ("TD", 1): "<Pumps_D>",
                ("T", 5): "</Pumps>",
                ("TD", 5): "</Pumps_D>",
            }
        )
        edit(store, ("T", 1, "comment", "<Tanks>"))
        assert comment(store, "TD", 1) == "<Tanks_D>"
        assert comment(store, "TD", 5) == "</Tanks_D>"

        # Right-click > Discard row changes sets all four fields to the base values.
        base = store.base_state[key("T", 1)]
        edit(
            store,
            ("T", 1, "nickname", base.nickname),
            ("T", 1, "comment", base.comment),
            ("T", 1, "initial_value", base.initial_value),
            ("T", 1, "retentive", base.retentive),
        )

        assert comment(store, "TD", 1) == "<Pumps_D>"
        assert comment(store, "T", 5) == "</Pumps>"
        assert comment(store, "TD", 5) == "</Pumps_D>"
        assert not store.has_unsaved_changes()

    def test_comment_and_retentive_together_reach_the_pair(self):
        store = make_store({})

        edit(store, ("T", 1, "comment", "<Mix />"), ("T", 1, "retentive", True))

        td1 = store.visible_state[key("TD", 1)]
        assert td1.comment == "<Mix_D />"
        assert td1.retentive is True


class TestWhatStillSyncs:
    """Add Block on T writes the _D tag on TD; Retentive mirrors across the pair."""

    def test_adding_a_block_on_t_tags_td(self):
        store = make_store({("TD", 1): "preset"})

        edit(store, ("T", 1, "comment", "<Timers>"), ("T", 3, "comment", "</Timers>"))

        assert comment(store, "TD", 1) == "preset <Timers_D>"
        assert comment(store, "TD", 3) == "</Timers_D>"

    @pytest.mark.parametrize(
        ("open_tag", "td_open_tag"),
        [("<Blk>", "<Blk_D>"), ('<Blk bg="Red">', '<Blk_D bg="Red">')],
    )
    def test_add_block_over_t_keeps_the_td_text(self, open_tag, td_open_tag):
        """Add Block over T1..T5 sets both T tags in one session; TD keeps its own text."""
        store = make_store({("TD", 1): "preset ms", ("TD", 5): "last preset"})

        edit(store, ("T", 1, "comment", open_tag), ("T", 5, "comment", "</Blk>"))

        assert comment(store, "TD", 1) == f"preset ms {td_open_tag}"
        assert comment(store, "TD", 5) == "last preset </Blk_D>"

    @pytest.mark.parametrize(
        ("open_tag", "td_open_tag"),
        [("<Blk>", "<Blk_D>"), ('<Blk bg="Red">', '<Blk_D bg="Red">')],
    )
    def test_add_block_over_t_replaces_the_old_td_tag_in_place(self, open_tag, td_open_tag):
        """T rows that held a block get the new one; TD's mirrored tag is replaced where it is."""
        store = make_store(
            {
                ("T", 1): "<Old>",
                ("T", 5): "</Old>",
                ("TD", 1): "<Old_D> preset ms",
                ("TD", 5): "last </Old_D> preset",
            }
        )

        edit(store, ("T", 1, "comment", open_tag), ("T", 5, "comment", "</Blk>"))

        assert comment(store, "TD", 1) == f"{td_open_tag} preset ms"
        assert comment(store, "TD", 5) == "last </Blk_D> preset"

    def test_adding_a_block_on_ctd_tags_ct(self):
        store = make_store({})

        edit(store, ("CTD", 2, "comment", "<Counts_D />"))

        assert comment(store, "CT", 2) == "<Counts />"

    def test_retentive_mirrors_from_td_to_t(self):
        store = make_store({})

        edit(store, ("TD", 7, "retentive", True))

        assert store.visible_state[key("T", 7)].retentive is True

    def test_a_pair_holding_another_block_is_left_alone(self):
        store = make_store({("T", 1): "<Timers>", ("TD", 1): "<Presets_D>"})

        edit(store, ("T", 1, "comment", "<Motors>"))

        assert comment(store, "TD", 1) == "<Presets_D>"
