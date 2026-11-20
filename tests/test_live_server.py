"""LiveServer runs queued commands on the Tk thread without waiting on dialogs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.connection_session import ClickConnection, ConnectionSession
from clicknick.data.address_store import AddressStore
from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.live.server import LiveServer, _Request
from clicknick.models.address_row import AddressRow
from clicknick.services.analysis_service import AnalysisService, AnalysisStatus
from clicknick.utils import mdb_operations


class MockDataSource:
    supports_used_field = True
    stored_row = staticmethod(mdb_operations.stored_row)
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
    stored_row = staticmethod(mdb_operations.stored_row)
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
    ("source", "advice"),
    [
        (MockDataSource(), "Sync them there to write them to CLICK's database."),
        (CsvSource(), "Save them there to write them to the CSV file."),
    ],
)
def test_prompt_save_says_sync_or_save_for_the_data_loaded(source, advice):
    reply, shown = _prompt(_edited_store(source))

    assert reply == "prompted: 1 row with unsaved edits"
    assert shown == [f"1 row in the Address Editor has unsaved edits.\n\n{advice}"]


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


_READING = "ClickNick is still reading CLICK's database. Try again when it has finished"
_NOT_LOADED = (
    "ClickNick has not loaded CLICK's database for this project. Select the window in the "
    "CLICK Windows list to load it"
)
_DATABASE_OFF = "Database access is off, because CLICKNICK_DB_BACKEND is set to none (CSV mode)"


def _session_in(state: str, monkeypatch, tmp_path: Path) -> ConnectionSession | None:
    """Return the session of a window in *state*, or None for "no window".

    In the "folder gone" state, the workspace folder is *tmp_path*/gone, which does not exist.
    """
    if state == "no window":
        return None
    session = ConnectionSession(ClickConnection("1", 2, "Main.ckp"))
    if state == "reading":
        session.begin_load()
    elif state == "access off":
        monkeypatch.setenv("CLICKNICK_DB_BACKEND", "none")
    elif state != "load failed":
        session.has_database = True
    if state == "building":
        session.analysis = AnalysisService()
        session.analysis.mark_building()
    elif state == "build cleared":
        # invalidate() leaves an analysis with no workspace, as when the user pairs another one
        session.analysis = AnalysisService()
        session.analysis.invalidate()
    elif state == "folder gone":
        session.analysis = AnalysisService()
        session.analysis._status = AnalysisStatus.READY
        session.analysis._project_dir = tmp_path / "gone"
    elif state.startswith("failed"):
        session.analysis = AnalysisService()
        session.analysis.mark_failed("no Scr*.tmp files" if state == "failed with reason" else "")
    return session


def _server(session: ConnectionSession | None, store: AddressStore | None) -> LiveServer:
    """Return a LiveServer wired to *session* the way ClickNickApp wires it."""
    return LiveServer(
        FakeRoot(),
        lambda: store,
        lambda: None,
        get_analysis=lambda: session.analysis if session else None,
        get_session=lambda: session,
    )


@pytest.mark.parametrize(
    ("state", "advice"),
    [
        ("no window", "Connect to a CLICK window, or use File > Load Nicknames from CSV."),
        ("reading", f"{_READING}."),
        ("access off", f"{_DATABASE_OFF}. Use File > Load Nicknames from CSV."),
        ("load failed", f"{_NOT_LOADED}, or use File > Load Nicknames from CSV."),
    ],
)
def test_without_addresses_a_command_says_why(monkeypatch, tmp_path, state, advice):
    """With a window connected, no addresses means that its database is loading or not loaded.

    Only with no window connected does the reply say to connect.
    """
    server = _server(_session_in(state, monkeypatch, tmp_path), store=None)

    with pytest.raises(ValueError) as caught:
        server.dispatch_now("get DS1")

    assert str(caught.value) == f"ClickNick has no addresses loaded. {advice}"


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("no window", "There is no workspace. Connect to a CLICK window first."),
        ("reading", f"There is no workspace. {_READING}."),
        ("access off", f"There is no workspace. {_DATABASE_OFF}."),
        ("load failed", f"There is no workspace. {_NOT_LOADED}."),
        (
            "not started",
            "There is no workspace. ClickNick has not started building the workspace. Save the"
            " project in CLICK, then try again.",
        ),
        (
            "build cleared",
            "There is no workspace. ClickNick has not started building the workspace. Save the"
            " project in CLICK, then try again.",
        ),
        (
            "building",
            "ClickNick is rebuilding the workspace from CLICK. Try again when it finishes.",
        ),
        ("failed with reason", "Could not build the workspace: no Scr*.tmp files"),
        ("failed without reason", "Could not build the workspace."),
        (
            "folder gone",
            "The workspace folder {gone} is gone. Use Workspace > Reload from CLICK.",
        ),
    ],
)
def test_without_a_workspace_a_command_says_why(monkeypatch, tmp_path, state, reason):
    """A command that needs the workspace gives the reason that ClickNick's windows give.

    It says to connect only when no window is connected. The windows have no reason for a
    workspace folder that was deleted after its build, so the reply names the folder.
    """
    server = _server(_session_in(state, monkeypatch, tmp_path), store=_edited_store(CsvSource()))

    with pytest.raises(ValueError) as caught:
        server.dispatch_now("rung list")

    assert str(caught.value) == reason.replace("{gone}", str(tmp_path / "gone"))


def test_the_reason_follows_the_connected_session():
    """The server reads the session each time, so the reply follows a connect."""
    sessions: list[ConnectionSession] = []
    server = LiveServer(
        FakeRoot(),
        lambda: None,
        lambda: None,
        get_session=lambda: sessions[-1] if sessions else None,
    )
    with pytest.raises(ValueError, match="Connect to a CLICK window"):
        server.dispatch_now("get DS1")

    sessions.append(ConnectionSession(ClickConnection("1", 2, "Main.ckp")))
    sessions[-1].begin_load()

    with pytest.raises(ValueError) as caught:
        server.dispatch_now("get DS1")
    assert str(caught.value) == f"ClickNick has no addresses loaded. {_READING}."
