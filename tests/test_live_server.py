"""LiveServer runs queued commands on the Tk thread without waiting on dialogs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.live.server import LiveServer, _Request
from clicknick.models.address_row import AddressRow


class MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False
    is_database = True

    def __init__(self, rows=None) -> None:
        self._rows = rows or {}

    def load_all_addresses(self):
        return self._rows

    def save_changes(self, rows):
        return len(rows)


class CsvSource(MockDataSource):
    supports_used_field = False
    file_path = "nicknames.csv"
    is_database = False


class FakeRoot:
    """Collects ``after`` callbacks. ``run_idle`` runs the ones that are due now."""

    def __init__(self) -> None:
        self.pending: list[tuple[int, object]] = []

    def after(self, ms, callback):
        self.pending.append((ms, callback))
        return f"after#{len(self.pending)}"

    def run_idle(self) -> None:
        due = [callback for ms, callback in self.pending if ms == 0]
        self.pending = [(ms, callback) for ms, callback in self.pending if ms != 0]
        for callback in due:
            callback()


def _edited_store(source: MockDataSource | None = None) -> AddressStore:
    store = AddressStore(source or MockDataSource())
    store.load_initial_data()
    with store.edit_session("edit") as session:
        session.set_field(get_addr_key("DS", 1), "nickname", "Level")
    return store


def _prompt(store: AddressStore) -> tuple[str, list[str]]:
    """Run prompt-save on *store*. Return the reply and the text of each dialog shown."""
    shown: list[str] = []
    ctx = DispatchContext(store=store, show_save_prompt=lambda _title, text: shown.append(text))
    return dispatch(ctx, "prompt-save"), shown


@pytest.mark.parametrize(
    ("source", "entry"),
    [
        (MockDataSource(), "Use File > Sync All there to write them to CLICK's database."),
        (CsvSource(), "Use File > Save All there to write them to the CSV file."),
    ],
)
def test_prompt_save_names_the_menu_entry_for_the_data_loaded(source, entry):
    reply, shown = _prompt(_edited_store(source))

    assert reply == "prompted: 1 row with unsaved edits"
    assert shown == [f"1 row in the Address Editor has unsaved edits.\n\n{entry}"]


def test_prompt_save_does_not_blame_the_edits_for_errors_in_other_rows():
    duplicate = {
        get_addr_key("DS", address): AddressRow(memory_type="DS", address=address, nickname="Dup")
        for address in (7, 8)
    }
    store = _edited_store(MockDataSource(duplicate))  # The edit is to DS1, which has no error.

    with pytest.raises(ValueError) as refused:
        _prompt(store)

    assert str(refused.value) == (
        "The Address Editor shows errors in 2 rows. Sync writes nothing while any row has an"
        " error. Fix those rows first."
    )


def test_prompt_save_answers_before_the_dialog_opens(monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        "tkinter.messagebox.showinfo", lambda title, _message, **_kw: shown.append(title)
    )
    root = FakeRoot()
    store = _edited_store()
    server = LiveServer(root, lambda: store, lambda: None)
    first, second = _Request("prompt-save"), _Request("prompt-save")
    server._queue.put(first)
    server._queue.put(second)

    server._drain()

    assert first.done.is_set() and first.result == "prompted: 1 row with unsaved edits"
    assert second.done.is_set()
    assert shown == []
    root.run_idle()
    assert shown == ["Unsaved Changes"]  # one dialog, not one per request


def test_commands_know_whether_click_saved_the_project(tmp_path: Path):
    server = LiveServer(
        FakeRoot(), lambda: None, lambda: None, get_mdb_path=lambda: tmp_path / "SC_.mdb"
    )
    assert server._build_context().project_saved is False

    (tmp_path / "Scr1.tmp").write_text("saved", encoding="utf-8")

    assert server._build_context().project_saved is True


def _analysis(*, analysis_tags: dict[str, int], workspace_tags: dict[str, int]):
    """Return a build that published the workspace with new names and then failed to analyse it."""
    return SimpleNamespace(
        is_available=bool(analysis_tags),
        tag_to_addr_key=analysis_tags,
        project_tag_to_addr_key=workspace_tags,
    )


def test_commands_find_tags_by_the_workspaces_names():
    level = get_addr_key("DS", 1)
    analysis = _analysis(analysis_tags={"Level": level}, workspace_tags={"Tank_Level": level})
    server = LiveServer(FakeRoot(), _edited_store, lambda: None, get_analysis=lambda: analysis)

    assert dispatch(server._build_context(), "get Tank_Level").startswith("Tank_Level (staged):")
    with pytest.raises(ValueError):
        dispatch(server._build_context(), "get Level")


def test_commands_find_tags_when_only_the_workspace_was_built():
    level = get_addr_key("DS", 1)
    analysis = _analysis(analysis_tags={}, workspace_tags={"Tank_Level": level})
    server = LiveServer(FakeRoot(), _edited_store, lambda: None, get_analysis=lambda: analysis)

    assert dispatch(server._build_context(), "get Tank_Level").startswith("Tank_Level (staged):")


@pytest.mark.parametrize("address", ["DS1u", "DS\u0661", "XD1u"])
def test_an_address_click_refuses_is_not_an_address(address):
    """A stray ``u`` or a non-ASCII digit is refused as CLICK refuses it, not read as DS1."""
    server = LiveServer(FakeRoot(), _edited_store, lambda: None)

    assert dispatch(server._build_context(), "get DS1").startswith("DS1 (staged):")
    assert dispatch(server._build_context(), "get XD0u").startswith("XD0u:")
    with pytest.raises(ValueError):
        dispatch(server._build_context(), f"get {address}")


def test_set_stores_and_reports_a_nickname_without_its_edge_spaces():
    store = _edited_store()
    server = LiveServer(FakeRoot(), lambda: store, lambda: None)

    reply = dispatch(server._build_context(), "set DS2 nickname ' Pump '")

    assert reply.startswith("OK: DS2 nickname = 'Pump' (staged change)")
    assert store.visible_state[get_addr_key("DS", 2)].nickname == "Pump"
