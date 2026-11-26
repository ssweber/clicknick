"""Test what the app does when ClickNick closes, CLICK closes or changes project, the app
connects, and a CSV loads.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.connection_controller import ConnectionController
from clicknick.connection_session import ClickConnection, ConnectionSession
from clicknick.data_session import DataSession
from clicknick.detection.window_detector import ClickInstance, ClickWindowDetector
from clicknick.services.workspace_mirror import ProjectWorkspaceConfig
from clicknick.utils.dialog_queue import DialogQueue
from clicknick.utils.win32_utils import WIN32
from clicknick.workspace_controller import WorkspaceController


class FakeVar:
    def __init__(self, value: str = ""):
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class FakeStore:
    def __init__(
        self, *, is_database: bool, unsaved: bool = False, save_error=None, source_path=None
    ):
        self.is_database = is_database
        self._data_source = SimpleNamespace(file_path=source_path)
        self._unsaved = unsaved
        self.load_initial_data = MagicMock()
        self.start_file_monitoring = MagicMock()
        self.add_sync_listener = MagicMock()
        self.stop_file_monitoring = MagicMock()
        self.save_all_changes = MagicMock(side_effect=save_error)

    def has_unsaved_changes(self) -> bool:
        return self._unsaved


class FakeEditor:
    def __init__(self) -> None:
        self.closed = False

    def commit_open_cell_editor(self) -> bool:
        return True

    def close_without_prompt(self) -> None:
        self.closed = True


class FakeDataview(FakeEditor):
    def __init__(self) -> None:
        super().__init__()
        self.saved = False
        self.refreshed = False

    def refresh_file_list(self) -> None:
        self.refreshed = True

    def has_unsaved_changes(self) -> bool:
        return True

    def save_all(self) -> bool:
        self.saved = True
        return True


class FakeRoot:
    """Records after() callbacks so a test can run them."""

    def __init__(self) -> None:
        self.scheduled: dict[str, tuple[int, object]] = {}
        self._next_id = 0
        self.destroy = MagicMock()

    def after(self, delay, callback):
        self._next_id += 1
        after_id = f"after#{self._next_id}"
        self.scheduled[after_id] = (delay, callback)
        return after_id

    def after_cancel(self, after_id) -> None:
        self.scheduled.pop(after_id, None)

    def pending(self, delay) -> int:
        return sum(1 for d, _cb in self.scheduled.values() if d == delay)

    def take(self, delay) -> list:
        """Remove and return the callbacks scheduled with *delay*."""
        ids = [after_id for after_id, (d, _cb) in self.scheduled.items() if d == delay]
        return [self.scheduled.pop(after_id)[1] for after_id in ids]


def _instance(pid: str, hwnd: int, filename: str) -> ClickInstance:
    return ClickInstance(pid, f"CLICK Programming Software - {filename}", filename, hwnd)


_MAIN = ClickConnection("111", 222, "Main.ckp")


def _session(click: ClickConnection = _MAIN):
    """Return a session on *click* whose close() calls are recorded."""
    session = ConnectionSession(click)
    session.close = MagicMock(wraps=session.close)
    return session


def _assert_loads(app: ClickNickApp, click: ClickConnection) -> None:
    """Assert that the database load started for a new session on *click*."""
    app._connection._load_instance_database.assert_called_once_with(app._session)
    assert app._session.click == click


def _app(monkeypatch, *, answer=None, yes_no=False) -> tuple[ClickNickApp, list]:
    """Build a ClickNickApp without Tk, connected to Main.ckp, with monitoring off.

    *answer* is the reply to Yes/No/Cancel questions. *yes_no* is the reply to Yes/No questions.
    """
    prompts: list = []
    monkeypatch.setattr(
        "tkinter.messagebox.askyesnocancel",
        lambda *args, **kwargs: prompts.append(args[:2]) or answer,
    )
    monkeypatch.setattr(
        "tkinter.messagebox.askyesno",
        lambda *args, **kwargs: prompts.append(("askyesno", *args[:2])) or yes_no,
    )
    monkeypatch.setattr(
        "tkinter.messagebox.showinfo", lambda *args, **kwargs: prompts.append(args[:1])
    )
    monkeypatch.setattr("tkinter.messagebox.showwarning", MagicMock())
    monkeypatch.setattr(
        "tkinter.messagebox.showerror",
        lambda *args, **kwargs: prompts.append(("showerror", *args[:2])),
    )
    app = ClickNickApp.__new__(ClickNickApp)
    app.__dict__["_ui_refresh_id"] = None
    app._connection = ConnectionController(app)
    app._request_ui_refresh = MagicMock()
    app.root = FakeRoot()
    app._dialogs = DialogQueue()
    app._session = _session()
    app._data = None
    app._update_status = MagicMock()
    app._connection.monitoring = False
    app._live_server = None
    app.start_button = MagicMock()
    app.nickname_manager = SimpleNamespace(set_store=MagicMock(), has_database_backend=lambda: True)
    app._connection.click_instances = [_instance("111", 222, "Main.ckp")]
    app.instances_combobox = {}
    app.selected_instance_var = FakeVar("Main.ckp")
    # CLICK's folder is not read
    monkeypatch.setattr(ConnectionSession, "load_workspace_pairing", lambda _self: None)
    app._connection._load_instance_database = MagicMock()
    app._remove_stale_compare_copies = MagicMock()
    app.detector = SimpleNamespace(
        check_window_exists=lambda _pid: True,
        get_window_title=lambda hwnd: next(
            (
                instance.title
                for instance in app._connection.click_instances
                if instance.hwnd == hwnd
            ),
            "",
        ),
        get_click_instances=lambda: list(app._connection.click_instances),
        detect_child_window=MagicMock(return_value=None),
    )
    app._workspace = WorkspaceController(app)
    return app, prompts


def _open(app: ClickNickApp, store: FakeStore) -> FakeEditor:
    app._data = DataSession(store)
    editor = FakeEditor()
    app._data.register_editor(editor)
    return editor


# -- app#1: closing ClickNick asks to save ----------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "closes", "saved"),
    [(None, False, False), (False, True, False), (True, True, True)],
    ids=["cancel", "discard", "save"],
)
def test_closing_clicknick_asks_to_save_unsaved_edits(monkeypatch, answer, closes, saved):
    app, prompts = _app(monkeypatch, answer=answer)
    store = FakeStore(is_database=True, unsaved=True)
    editor = _open(app, store)
    session = app._session

    app.on_closing()

    assert prompts == [
        ("Unsaved Changes", "You have unsaved address changes. Save before closing?")
    ]
    assert store.save_all_changes.called is saved
    assert editor.closed is closes
    assert app.root.destroy.called is closes
    assert session.close.called is closes
    assert (app._data is None) is closes


def test_closing_clicknick_stays_open_when_the_save_fails(monkeypatch):
    app, _prompts = _app(monkeypatch, answer=True)
    store = FakeStore(is_database=True, unsaved=True, save_error=OSError("locked"))
    editor = _open(app, store)

    app.on_closing()

    assert not app.root.destroy.called
    assert not editor.closed
    assert app._data.store is store


def test_closing_clicknick_asks_about_dataview_edits(monkeypatch):
    app, prompts = _app(monkeypatch, answer=True)
    app._data = DataSession(FakeStore(is_database=True))
    dataview = FakeDataview()
    app._data.register_dataview_window(dataview)

    app.on_closing()

    assert prompts == [
        (
            "Unsaved Changes",
            "You have unsaved changes in the Data View Editor. Save before closing?",
        )
    ]
    assert dataview.saved and dataview.closed
    assert app.root.destroy.called


# -- app#2: a project change keeps CSV data ---------------------------------------------------


def test_project_change_keeps_csv_data_with_unsaved_edits(monkeypatch):
    app, prompts = _app(monkeypatch)
    store = FakeStore(is_database=False, unsaved=True, source_path="C:/Users/me/Main_Address.csv")
    editor = _open(app, store)
    app._connection.monitoring = True
    session = app._session

    app._connection._handle_project_change("CLICK Programming Software - Main2.ckp", "Main2.ckp")

    assert prompts == []
    assert app._data.store is store
    assert not editor.closed
    store.stop_file_monitoring.assert_not_called()
    assert not store.save_all_changes.called
    assert app._csv_path == "C:/Users/me/Main_Address.csv"
    assert app._click == ClickConnection("111", 222, "Main2.ckp")
    assert app.selected_instance_var.get() == "Main2.ckp"
    assert app._connection.monitoring
    session.close.assert_called_once()
    app._connection._load_instance_database.assert_not_called()


def _set_pending_choice(app, tmp_path) -> None:
    app._session.setup_window = MagicMock()
    app._session.pending_workspace = ProjectWorkspaceConfig("Main", tmp_path / "Chosen")


def test_project_change_warns_when_workspace_setup_held_a_choice_not_applied(monkeypatch, tmp_path):
    warning = MagicMock()
    app, _ = _app(monkeypatch)
    monkeypatch.setattr("clicknick.connection_controller.messagebox.showwarning", warning)
    _open(app, FakeStore(is_database=False))
    _set_pending_choice(app, tmp_path)

    app._connection._handle_project_change("CLICK Programming Software - Main2.ckp", "Main2.ckp")

    warning.assert_called_once()
    assert warning.call_args.args[0] == "Workspace"
    assert warning.call_args.args[1].startswith(
        "Workspace setup closed because the project in CLICK changed."
    )
    assert warning.call_args.kwargs["parent"] is app.root


def test_project_change_shows_the_warning_once_through_the_database_load(monkeypatch, tmp_path):
    """The warning is a dialog, so the load's later status lines cannot hide it."""
    warning = MagicMock()
    monkeypatch.setattr("clicknick.data.data_source.MdbDataSource", lambda **_kw: MagicMock())
    monkeypatch.setattr(
        "clicknick.connection_controller.AddressStore",
        lambda _source: MagicMock(load_initial_data=MagicMock()),
    )
    app, _ = _app(monkeypatch)
    monkeypatch.setattr("clicknick.connection_controller.messagebox.showwarning", warning)
    app._connection._load_instance_database = ConnectionController._load_instance_database.__get__(
        app._connection
    )
    app._connection._on_data_ready = MagicMock()
    app._open_data = MagicMock(
        side_effect=lambda store, **_kw: setattr(app, "_data", DataSession(store)) or True
    )
    app._start_analysis_build = MagicMock()
    _open(app, FakeStore(is_database=True))
    _set_pending_choice(app, tmp_path)

    app._connection._handle_project_change("CLICK Programming Software - Main2.ckp", "Main2.ckp")

    for _ in range(200):
        for callback in app.root.take(100):
            callback()
        if app._open_data.called:
            break
        time.sleep(0.01)
    assert app._open_data.called
    warning.assert_called_once()
    app._update_status.assert_any_call("✓ DB loaded", "connected")


def test_project_change_shows_no_warning_without_a_pending_choice(monkeypatch):
    warning = MagicMock()
    monkeypatch.setattr("clicknick.connection_controller.messagebox.showwarning", warning)
    app, _ = _app(monkeypatch)
    _open(app, FakeStore(is_database=False))

    app._connection._handle_project_change("CLICK Programming Software - Main2.ckp", "Main2.ckp")

    warning.assert_not_called()


def test_project_change_closes_database_data_and_loads_the_new_project(monkeypatch):
    app, prompts = _app(monkeypatch)
    editor = _open(app, FakeStore(is_database=True))

    app._connection._handle_project_change("CLICK Programming Software - Main2.ckp", "Main2.ckp")

    assert prompts == [("Project Changed",)]
    assert editor.closed
    assert app._data is None
    _assert_loads(app, ClickConnection("111", 222, "Main2.ckp"))


# -- app#11: a project change asks about unsaved database edits ---------------------------------


def test_project_change_can_keep_unsaved_database_edits_for_the_new_project(monkeypatch):
    sessions = []
    monkeypatch.setattr(
        "clicknick.connection_session.ConnectionSession",
        lambda click, **kw: (
            sessions.append((click, kw["has_database"]))
            or MagicMock(click=click, simulator=None, synced_pending=0)
        ),
    )
    app, prompts = _app(monkeypatch, yes_no=True)
    store = FakeStore(is_database=True, unsaved=True)
    editor = _open(app, store)
    old_session = app._session

    app._connection._handle_project_change(
        "CLICK Programming Software - Renamed.ckp", "Renamed.ckp"
    )

    ((_, title, message),) = prompts
    assert title == "Project Changed"
    assert "Keep them as unsaved changes for Renamed.ckp?" in message
    assert "Sync writes the address changes to Renamed.ckp." in message
    assert "Choose Yes if you used Save As in CLICK." in message
    assert "Data View" not in message
    assert app._data.store is store
    assert not editor.closed
    # The store's file monitor keeps running. It reads the saved data under the kept edits
    # from the new project's database.
    store.stop_file_monitoring.assert_not_called()
    assert not store.save_all_changes.called
    app._connection._load_instance_database.assert_not_called()
    old_session.close.assert_called_once()
    # The kept edits are on database data, so the new session has a database and starts its
    # build at once.
    assert sessions == [(ClickConnection("111", 222, "Renamed.ckp"), True)]
    app._session.start_analysis.assert_called_once_with(app.root)
    assert app._click == ClickConnection("111", 222, "Renamed.ckp")
    assert app._window_title() == "ClickNick - Renamed.ckp - DB"


def test_project_change_can_discard_unsaved_database_edits(monkeypatch):
    app, prompts = _app(monkeypatch, yes_no=False)
    store = FakeStore(is_database=True, unsaved=True)
    editor = _open(app, store)

    app._connection._handle_project_change("CLICK Programming Software - Other.ckp", "Other.ckp")

    assert [prompt[:2] for prompt in prompts] == [
        ("askyesno", "Project Changed"),
        ("Project Changed",),
    ]
    assert editor.closed
    assert not store.save_all_changes.called
    assert app._data is None
    _assert_loads(app, ClickConnection("111", 222, "Other.ckp"))


def test_project_change_counts_text_still_in_a_cell_editor(monkeypatch):
    app, prompts = _app(monkeypatch, yes_no=True)
    store = FakeStore(is_database=True)
    editor = _open(app, store)
    editor.commit_open_cell_editor = lambda: setattr(store, "_unsaved", True) or True

    app._connection._handle_project_change(
        "CLICK Programming Software - Renamed.ckp", "Renamed.ckp"
    )

    assert [prompt[:2] for prompt in prompts] == [("askyesno", "Project Changed")]
    assert app._data.store is store


@pytest.mark.parametrize("keep", [True, False], ids=["keep", "discard"])
def test_project_change_asks_one_question_about_dataview_edits(monkeypatch, keep):
    """After File > Open, the app asks once whether to keep or discard the Dataview edits.

    The window's DataView folder then holds the other project's .cdv files, so the app never
    saves the edits over those files.
    """
    monkeypatch.setattr(
        "clicknick.connection_session.ConnectionSession",
        lambda click, **_kw: MagicMock(click=click, simulator=None, synced_pending=0),
    )
    app, prompts = _app(monkeypatch, yes_no=keep)
    store = FakeStore(is_database=True)
    app._data = DataSession(store)
    dataview = FakeDataview()
    app._data.register_dataview_window(dataview)

    app._connection._handle_project_change("CLICK Programming Software - Other.ckp", "Other.ckp")

    (question, *notices) = prompts
    assert question[:2] == ("askyesno", "Project Changed")
    assert "Data View changes" in question[2]
    assert not dataview.saved
    if keep:
        assert notices == []
        assert not dataview.closed
        assert app._data.store is store
        app._connection._load_instance_database.assert_not_called()
    else:
        assert notices == [("Project Changed",)]
        assert dataview.closed
        assert app._data is None
        _assert_loads(app, ClickConnection("111", 222, "Other.ckp"))


def test_project_change_asks_when_a_cell_editor_will_not_commit(monkeypatch):
    """A cell editor that cannot commit its text still counts as an unsaved change.

    When CLICK has the focus, the open cell editor cannot commit. The app asks before it
    drops the text.
    """
    app, prompts = _app(monkeypatch, yes_no=False)
    editor = _open(app, FakeStore(is_database=True))
    editor.commit_open_cell_editor = lambda: False

    app._connection._handle_project_change("CLICK Programming Software - Other.ckp", "Other.ckp")

    assert prompts[0][:2] == ("askyesno", "Project Changed")


# -- The window list always shows the connected window --------------------------------------------


def test_connecting_by_itself_selects_the_window_in_the_list(monkeypatch):
    monkeypatch.setattr("clicknick.utils.mdb_shared.get_database_backend", lambda: "odbc")
    app, _prompts = _app(monkeypatch)
    app._session = None
    app.selected_instance_var = FakeVar("")

    app._connection.refresh_click_instances()

    assert app._click == ClickConnection("111", 222, "Main.ckp")
    assert app.instances_combobox["values"] == ["Main.ckp"]
    assert app.selected_instance_var.get() == "Main.ckp"


def test_a_project_change_lists_a_window_the_list_left_out(monkeypatch):
    app, _prompts = _app(monkeypatch)
    _open(app, FakeStore(is_database=False))
    # This list was read while the window's title showed no project.
    app.detector.get_click_instances = lambda: []
    app._connection.refresh_click_instances()
    assert app.instances_combobox["values"] == ["Main.ckp"]

    app._connection._handle_project_change("CLICK Programming Software - follow.ckp", "follow.ckp")

    assert app.instances_combobox["values"] == ["follow.ckp"]
    assert app.selected_instance_var.get() == "follow.ckp"
    (listed,) = app._connection.click_instances
    assert listed == ClickInstance(
        "111", "CLICK Programming Software - follow.ckp", "follow.ckp", 222
    )
    app.selected_instance_var.set("follow.ckp")
    app._connection.connect_to_instance = MagicMock()
    app._connection.on_instance_selected()
    app._connection.connect_to_instance.assert_called_once()


# -- app#3: the CSV path is the open data's -----------------------------------------------------


def _patch_csv(monkeypatch, *, fails: bool = False) -> None:
    def source(path):
        if fails:
            raise ValueError("bad csv")
        return SimpleNamespace(path=path)

    monkeypatch.setattr("clicknick.data.data_source.CsvDataSource", source)
    monkeypatch.setattr(
        "clicknick.connection_controller.AddressStore",
        lambda source: FakeStore(is_database=False, source_path=source.path),
    )


@pytest.mark.parametrize("fails", [False, True], ids=["cancelled", "failed"])
def test_a_csv_load_that_does_not_open_leaves_the_database_data(monkeypatch, fails):
    _patch_csv(monkeypatch, fails=fails)
    app, _prompts = _app(monkeypatch, answer=None)
    db_store = FakeStore(is_database=True, unsaved=True)
    _open(app, db_store)
    monkeypatch.setattr(
        "clicknick.app.filedialog.askopenfilename", lambda **_kw: "C:/tmp/Other.csv"
    )

    app.browse_and_load_csv()

    assert app._data.store is db_store
    assert app._csv_path is None
    assert app._window_title() == "ClickNick - Main.ckp - DB"

    # After a CLICK Save As, the app reloads the database under the new name.
    app._connection._handle_project_change(
        "CLICK Programming Software - Renamed.ckp", "Renamed.ckp"
    )
    _assert_loads(app, ClickConnection("111", 222, "Renamed.ckp"))


def test_a_csv_load_sets_the_csv_path_with_the_data(monkeypatch):
    _patch_csv(monkeypatch)
    app, _prompts = _app(monkeypatch)

    assert app._connection.load_csv("C:/tmp/Other.csv")

    assert app._csv_path == "C:/tmp/Other.csv"
    assert app._window_title() == "ClickNick - Main.ckp - CSV"

    app._close_data(prompt_save=False)
    assert app._csv_path is None
    assert app._window_title() == "ClickNick - Main.ckp"


# -- app#4: no auto-connect while data is loaded ------------------------------------------------


def test_refresh_after_the_window_closed_lists_windows_without_connecting(monkeypatch):
    app, _prompts = _app(monkeypatch)
    store = FakeStore(is_database=False, unsaved=True)
    editor = _open(app, store)
    app._connection.connect_to_instance = MagicMock()
    other = _instance("333", 444, "Other.ckp")
    app.detector.get_click_instances = lambda: [other]

    app._connection._handle_window_closed()
    (refresh,) = app.root.take(2000)
    refresh()

    app._connection.connect_to_instance.assert_not_called()
    assert app.instances_combobox["values"] == ["Other.ckp"]
    assert app.selected_instance_var.get() == ""
    assert app._data.store is store
    assert not editor.closed


def test_refresh_with_nothing_loaded_connects_to_the_first_window(monkeypatch):
    app, _prompts = _app(monkeypatch)
    app._session = None
    app._connection.connect_to_instance = MagicMock()
    other = _instance("333", 444, "Other.ckp")
    app.detector.get_click_instances = lambda: [other]

    app._connection.refresh_click_instances()

    app._connection.connect_to_instance.assert_called_once_with(
        "333", other.title, "Other.ckp", 444
    )


# -- The session opens on connect, before the database loads ----------------------------------


def test_connecting_opens_the_session_before_the_database_loads(monkeypatch):
    monkeypatch.setattr("clicknick.utils.mdb_shared.get_database_backend", lambda: "odbc")
    app, _prompts = _app(monkeypatch)
    app._session = None

    app._connection.connect_to_instance(
        "111", "CLICK Programming Software - Main.ckp", "Main.ckp", 222
    )

    _assert_loads(app, ClickConnection("111", 222, "Main.ckp"))
    assert not app._session.has_database
    assert app._window_title() == "ClickNick - Main.ckp"


@pytest.mark.parametrize(
    ("owner", "action"),
    [
        ("workspace", "review_changes"),
        ("workspace", "reload_from_click"),
        ("app", "_open_simulator"),
        ("app", "_toggle_simulation"),
        ("workspace", "_apply_setup"),
        ("workspace", "_ensure_plc_name"),
    ],
)
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("no window", "⚠ Connect to a CLICK window first"),
        (
            "reading",
            "⚠ ClickNick is still reading CLICK's database. Try again when it has finished",
        ),
        (
            "not loaded",
            "⚠ ClickNick has not loaded CLICK's database for this project. Select the window "
            "in the CLICK Windows list to load it",
        ),
    ],
)
def test_without_its_database_a_session_says_why_it_cannot_act(
    monkeypatch, owner, action, state, expected
):
    """These need CLICK's database, and each says why it is missing and what to do.

    With a window connected, the app has a session for it. The database is still loading, or
    ClickNick did not load it (the load failed or was cancelled, or a CSV file was loaded).
    """
    app, _prompts = _app(monkeypatch)
    app._live_server = MagicMock()
    app._workspace.plc_name = MagicMock(return_value=None)
    session = app._session
    if state == "no window":
        app._session = None
    elif state == "reading":
        session.begin_load()

    getattr(app._workspace if owner == "workspace" else app, action)()

    ((message, style),) = [call.args for call in app._update_status.call_args_list]
    assert (message, style) == (expected, "error")
    app._live_server.dispatch_now.assert_not_called()
    assert session.analysis is None and session.simulation is None


def test_a_finished_database_load_is_no_longer_reading():
    session = _session()
    session.begin_load()
    assert session.reading_database

    session.end_load()

    assert not session.reading_database


def test_cancelling_the_plc_name_prompt_in_workspace_setup_shows_nothing(monkeypatch, tmp_path):
    """The user is connected and only cancelled, so no status says to connect first."""
    from clicknick.services.workspace_mirror import ProjectWorkspaceConfig

    app, prompts = _app(monkeypatch)
    app._session.has_database = True
    app._session.pending_workspace = ProjectWorkspaceConfig(
        plc_name="Line1", workspace_path=tmp_path / "Line1"
    )
    app._workspace.plc_name = MagicMock(return_value=None)
    asked = []
    monkeypatch.setattr(
        "tkinter.simpledialog.askstring", lambda *args, **kwargs: asked.append(args[0])
    )

    app._workspace._apply_setup()

    assert asked == ["Name PLC"]
    app._update_status.assert_not_called()
    assert prompts == []


# -- app#5: Stop turns off popups only -----------------------------------------------------------


def test_stopped_monitoring_still_notices_click_closing(monkeypatch):
    app, _prompts = _app(monkeypatch)
    editor = _open(app, FakeStore(is_database=True, unsaved=True))
    session = app._session
    app._connection.refresh_click_instances = MagicMock()

    app._connection.button_start_monitoring()
    app._connection.stop_monitoring()
    app.detector.check_window_exists = lambda _pid: False
    for tick in app.root.take(100):
        tick()

    session.close.assert_called_once()
    assert editor.closed
    assert app._click is None
    assert app.root.pending(100) == 0


def test_the_watch_keeps_the_data_when_one_window_check_fails(monkeypatch):
    app, _prompts = _app(monkeypatch)
    editor = _open(app, FakeStore(is_database=True, unsaved=True))
    session = app._session

    def win_exist(**_kwargs):
        raise OSError("EnumWindows failed")

    monkeypatch.setattr(WIN32, "win_exist", win_exist)
    app.detector.check_window_exists = ClickWindowDetector({}, None).check_window_exists

    app._connection._watch_connection()  # The watch's first tick runs at once

    session.close.assert_not_called()
    assert not editor.closed
    assert app._session is session
    assert app.root.pending(100) == 1


def test_stopped_monitoring_still_notices_a_project_change(monkeypatch):
    app, _prompts = _app(monkeypatch)
    _open(app, FakeStore(is_database=True))
    app.detector.get_window_title = lambda _hwnd: "CLICK Programming Software - Next.ckp"

    app._connection._watch_connection()

    _assert_loads(app, ClickConnection("111", 222, "Next.ckp"))
    app.detector.detect_child_window.assert_not_called()
    assert app.root.pending(100) == 1


# The titles of CLICK's window during File > New, from a live run of CLICK 4.00 that started on
# an unsaved NewProject1.ckp. CLICK named the new project NewProject1.ckp too.
_NEW_PROJECT1 = "CLICK Programming Software (Version4.00) - NewProject1.ckp - [Main Program]"
_FILE_NEW_TITLES = [
    _NEW_PROJECT1,
    "CLICK Programming Software (Version4.00) - NewProject1.ckp",
    "CLICK Programming Software (Version4.00)",
    "CLICK Programming Software (Version4.00) - NewProject1.ckp",
    _NEW_PROJECT1,
]


def _watch_titles(app: ClickNickApp, titles: list[str | None]) -> None:
    """Start the watch, and run one tick for each title in *titles*, in order."""
    for n, title in enumerate(titles):
        app.detector.get_window_title = lambda _hwnd, title=title: title
        if n == 0:
            app._connection._watch_connection()
        else:
            (tick,) = app.root.take(100)
            tick()


def test_file_new_that_reuses_the_file_name_is_another_project(monkeypatch):
    app, prompts = _app(monkeypatch, yes_no=False)
    click = ClickConnection("111", 222, "NewProject1.ckp")
    app._session = old_session = _session(click)
    editor = _open(app, FakeStore(is_database=True, unsaved=True))

    _watch_titles(app, _FILE_NEW_TITLES)

    assert [prompt[:2] for prompt in prompts] == [
        ("askyesno", "Project Changed"),
        ("Project Changed",),
    ]
    # Save As never shows a title without a project, so the question does not suggest one.
    assert "Save As" not in prompts[0][2]
    old_session.close.assert_called_once()
    assert editor.closed
    assert app._data is None
    assert app._session is not old_session
    _assert_loads(app, click)
    assert app.root.pending(100) == 1


def test_file_open_of_a_project_with_the_same_file_name_is_another_project(monkeypatch):
    app, prompts = _app(monkeypatch)
    click = ClickConnection("111", 222, "Plant.ckp")
    app._session = old_session = _session(click)
    editor = _open(app, FakeStore(is_database=True))

    _watch_titles(
        app,
        [
            "CLICK Programming Software (Version4.00) - Plant.ckp - [Main Program]",
            "CLICK Programming Software (Version4.00) - Plant.ckp",
            "CLICK Programming Software (Version4.00)",
            "CLICK Programming Software (Version4.00) - Plant.ckp - [Main Program]",
        ],
    )

    assert prompts == [("Project Changed",)]
    old_session.close.assert_called_once()
    assert editor.closed
    assert app._data is None
    _assert_loads(app, click)


def test_kept_edits_after_file_new_go_to_a_new_session(monkeypatch):
    monkeypatch.setattr(ConnectionSession, "start_analysis", MagicMock())
    app, prompts = _app(monkeypatch, yes_no=True)
    click = ClickConnection("111", 222, "NewProject1.ckp")
    app._session = old_session = _session(click)
    store = FakeStore(is_database=True, unsaved=True)
    editor = _open(app, store)

    _watch_titles(app, _FILE_NEW_TITLES)

    ((_, title, message),) = prompts
    assert title == "Project Changed"
    assert "Keep them as unsaved changes for NewProject1.ckp?" in message
    assert "Save As" not in message
    assert app._data.store is store
    assert not editor.closed
    app._connection._load_instance_database.assert_not_called()
    old_session.close.assert_called_once()
    new_session = app._session
    assert new_session is not old_session
    assert new_session.click == click
    assert new_session.has_database
    assert not new_session.project_unloaded
    new_session.start_analysis.assert_called_once_with(app.root)


@pytest.mark.parametrize("unread", [None, ""], ids=["none", "empty"])
def test_a_title_that_cannot_be_read_is_not_a_project_change(monkeypatch, unread):
    app, prompts = _app(monkeypatch)
    app._session = session = _session(ClickConnection("111", 222, "NewProject1.ckp"))
    _open(app, FakeStore(is_database=True, unsaved=True))

    _watch_titles(app, [_NEW_PROJECT1, unread, _NEW_PROJECT1])

    assert prompts == []
    session.close.assert_not_called()
    assert app._session is session
    app._connection._load_instance_database.assert_not_called()


def test_the_popup_goes_with_the_window_it_was_shown_over(monkeypatch):
    overlay = MagicMock()
    overlay.is_active.return_value = False
    monkeypatch.setattr("clicknick.connection_controller.Overlay", MagicMock(return_value=overlay))
    app, _prompts = _app(monkeypatch)
    _open(app, FakeStore(is_database=False))
    app._connection.refresh_click_instances = MagicMock()
    session = app._session
    app.detector.detect_child_window.return_value = SimpleNamespace(
        window_id=7, window_class="#32770", edit_control="Edit1"
    )
    app.detector.field_has_text = lambda _control, _window: False
    app.detector.update_window_info = lambda *_args: SimpleNamespace(allowed_address_types=[])

    app._connection.button_start_monitoring()
    assert session.overlay is overlay
    overlay.show_combobox.assert_called_once_with([])

    app.detector.check_window_exists = lambda _pid: False
    (tick,) = app.root.take(100)
    tick()

    overlay.withdraw.assert_called_once_with()
    overlay.destroy.assert_called_once_with()
    assert session.overlay is None and app._session is None
    assert app.root.pending(100) == 0


def test_workspace_setup_closes_with_the_click_window(monkeypatch):
    warning = MagicMock()
    app, _prompts = _app(monkeypatch)
    monkeypatch.setattr("clicknick.connection_controller.messagebox.showwarning", warning)
    app._connection.refresh_click_instances = MagicMock()
    session = app._session
    setup = MagicMock()
    session.setup_window = setup
    session.pending_workspace = object()

    app._connection._watch_connection()
    app.detector.check_window_exists = lambda _pid: False
    (tick,) = app.root.take(100)
    tick()

    assert app._session is None
    setup.destroy.assert_called_once_with()
    assert session.setup_window is None and session.pending_workspace is None
    warning.assert_called_once()


def test_the_new_project_is_watched_even_when_following_it_fails(monkeypatch):
    app, _prompts = _app(monkeypatch)
    _open(app, FakeStore(is_database=True))
    app.detector.get_window_title = lambda _hwnd: "CLICK Programming Software - Next.ckp"

    def unreadable(**_kwargs):
        raise OSError("DataView folder unreadable")

    app._connection._reopen_dataview_editor = unreadable

    with pytest.raises(OSError):
        app._connection._watch_connection()

    assert app._click == ClickConnection("111", 222, "Next.ckp")
    assert app.root.pending(100) == 1


def test_a_database_load_whose_session_closed_during_the_save_prompt_is_dropped(monkeypatch):
    app, _prompts = _app(monkeypatch)
    old = FakeStore(is_database=False)
    _open(app, old)
    session = app._session
    token = session.begin_load()
    new = FakeStore(is_database=True)

    def close_during_prompt(_root, *, prompt_save):
        session.close()  # CLICK's window closed while the prompt was up
        return True

    app._data.close = close_during_prompt

    assert not app._open_data(new, still_wanted=lambda: session.loads(token))
    new.start_file_monitoring.assert_not_called()
    assert app._data is None
    app.nickname_manager.set_store.assert_called_once_with(None)


def test_popup_detection_runs_only_while_monitoring(monkeypatch):
    app, _prompts = _app(monkeypatch)
    _open(app, FakeStore(is_database=True))

    app._connection.button_start_monitoring()
    app.detector.detect_child_window.assert_called_once_with("111")
    app._connection.stop_monitoring()
    (tick,) = app.root.take(100)
    tick()

    app.detector.detect_child_window.assert_called_once_with("111")
    assert app.root.pending(100) == 1


def test_connecting_starts_the_watch_before_data_loads(monkeypatch):
    monkeypatch.setattr("clicknick.utils.mdb_shared.get_database_backend", lambda: "odbc")
    app, _prompts = _app(monkeypatch)
    app._session = None

    app._connection.connect_to_instance(
        "111", "CLICK Programming Software - Main.ckp", "Main.ckp", 222
    )
    app._connection.connect_to_instance(
        "111", "CLICK Programming Software - Main.ckp", "Main.ckp", 222
    )

    # Only the second session's watch remains, because closing the first session ended its own.
    assert app.root.pending(100) == 1


@pytest.mark.parametrize("process_alive", [False, True], ids=["gone", "alive"])
def test_refresh_closes_a_missing_window_only_when_its_process_is_gone(monkeypatch, process_alive):
    app, prompts = _app(monkeypatch)
    store = FakeStore(is_database=True, unsaved=True)
    editor = _open(app, store)
    session = app._session
    # The list omits a window whose title shows no project. It is also empty after an error.
    app.detector.get_click_instances = lambda: []
    app.detector.check_window_exists = lambda _pid: process_alive

    app._connection.refresh_click_instances()

    assert prompts == []
    if process_alive:
        session.close.assert_not_called()
        assert not editor.closed
        assert app._data.store is store
        assert app._click == ClickConnection("111", 222, "Main.ckp")
    else:
        session.close.assert_called_once()
        assert editor.closed
        assert app._session is None and app._data is None and app._click is None


# -- app#7, #8: picking a window -----------------------------------------------------------------


def test_two_windows_with_one_filename_can_each_be_picked(monkeypatch):
    app, _prompts = _app(monkeypatch)
    app._session = None
    app._connection.connect_to_instance = MagicMock()
    first, second = _instance("1", 0x10, "Main.ckp"), _instance("2", 0x20, "Main.ckp")
    app.detector.get_click_instances = lambda: [first, second]
    app._data = DataSession(FakeStore(is_database=False))  # So the refresh connects to nothing
    app._connection.refresh_click_instances()

    labels = app.instances_combobox["values"]
    assert labels == ["Main.ckp (PID 1)", "Main.ckp (PID 2)"]
    app.selected_instance_var.set(labels[1])
    app._connection.on_instance_selected()

    app._connection.connect_to_instance.assert_called_once_with(
        "2", second.title, "Main.ckp", 0x20, user_picked=True
    )


def test_cancelling_a_switch_shows_the_connected_window_again(monkeypatch):
    app, prompts = _app(monkeypatch, answer=None)
    store = FakeStore(is_database=False, unsaved=True)
    _open(app, store)
    other = _instance("333", 444, "Other.ckp")
    app._connection.click_instances.append(other)
    app.selected_instance_var.set("Other.ckp")

    app._connection.connect_to_instance("333", other.title, "Other.ckp", 444)

    assert len(prompts) == 1
    assert app._data.store is store
    assert app._click == ClickConnection("111", 222, "Main.ckp")
    assert app.selected_instance_var.get() == "Main.ckp"


# -- app#9: the delayed Monitoring status ---------------------------------------------------------


def test_delayed_monitoring_status_does_not_overwrite_a_later_one(monkeypatch):
    app, _prompts = _app(monkeypatch)
    app._connection.refresh_click_instances = MagicMock()
    app._connection.monitoring = True

    app._connection._on_data_ready()
    (show_status,) = app.root.take(1000)
    app.detector.check_window_exists = lambda _pid: False
    for tick in app.root.take(100):
        tick()
    app._update_status.reset_mock()
    app.start_button.reset_mock()
    show_status()

    app._update_status.assert_not_called()
    app.start_button.configure.assert_not_called()


# -- Stop sticks until the user starts monitoring or picks a window ----------------------------


def _assert_stopped(app: ClickNickApp) -> None:
    assert app._connection.monitoring is False
    assert app.start_button.configure.call_args.kwargs == {"text": "▶ Start"}
    assert app.root.pending(1000) == 0


def _stopped_app(monkeypatch, *, answer=None) -> tuple[ClickNickApp, list]:
    app, prompts = _app(monkeypatch, answer=answer)
    app._connection.monitoring = True
    app._connection.stop_monitoring()
    return app, prompts


def test_stop_sticks_through_a_project_change(monkeypatch):
    app, _prompts = _stopped_app(monkeypatch)
    _open(app, FakeStore(is_database=True))
    app.detector.get_window_title = lambda _hwnd: "CLICK Programming Software - Next.ckp"

    app._connection._watch_connection()
    _assert_loads(app, ClickConnection("111", 222, "Next.ckp"))
    # This is what the background load does once it has read the new database.
    app._open_data(FakeStore(is_database=True))
    assert app._connection.load_from_database()

    _assert_stopped(app)


def test_stop_sticks_through_the_csv_fallback(monkeypatch):
    _patch_csv(monkeypatch)
    app, _prompts = _stopped_app(monkeypatch)
    app._show_main_window = MagicMock()
    monkeypatch.setattr(
        "clicknick.connection_controller.find_fallback_csv", lambda _hwnd: "Address.csv"
    )
    dialog = MagicMock()
    dialog.return_value.show.return_value = "C:/tmp/Main_Address.csv"
    monkeypatch.setattr("clicknick.connection_controller.CsvFallbackDialog", dialog)

    app._connection._connect_csv_fallback("Main.ckp", 222)

    assert app._csv_path == "C:/tmp/Main_Address.csv"
    _assert_stopped(app)


def test_no_csv_chosen_says_nothing_is_loaded_without_saying_stopped(monkeypatch):
    app, _prompts = _app(monkeypatch)
    app._connection.monitoring = True
    app._connection._odbc_warning_shown = True
    app._show_main_window = MagicMock()
    monkeypatch.setattr("clicknick.connection_controller.find_fallback_csv", lambda _hwnd: None)

    app._connection._connect_csv_fallback("Main.ckp", 222)

    app._update_status.assert_called_once_with(
        "No nicknames loaded. Use File > Load Nicknames from CSV", "error"
    )
    assert app._connection.monitoring is True


def test_stop_sticks_when_a_refresh_connects_after_the_window_closed(monkeypatch):
    monkeypatch.setattr("clicknick.utils.mdb_shared.get_database_backend", lambda: "odbc")
    app, _prompts = _stopped_app(monkeypatch)
    _open(app, FakeStore(is_database=True))
    other = _instance("333", 444, "Other.ckp")
    app.detector.check_window_exists = lambda pid: pid == "333"
    app.detector.get_click_instances = lambda: [other]

    app._connection._watch_connection()
    assert app._click is None and app._data is None
    (refresh,) = app.root.take(2000)
    refresh()
    _assert_loads(app, ClickConnection("333", 444, "Other.ckp"))
    app._open_data(FakeStore(is_database=True))
    app._connection.load_from_database()

    assert app._click == ClickConnection("333", 444, "Other.ckp")
    _assert_stopped(app)


def test_picking_a_window_turns_monitoring_on(monkeypatch):
    monkeypatch.setattr("clicknick.utils.mdb_shared.get_database_backend", lambda: "odbc")
    app, _prompts = _stopped_app(monkeypatch)
    other = _instance("333", 444, "Other.ckp")
    app._connection.click_instances.append(other)
    app.selected_instance_var.set("Other.ckp")

    app._connection.on_instance_selected()

    assert app._connection.monitoring is True
    assert app.start_button.configure.call_args.kwargs == {"text": "⏹ Stop"}


# -- A CSV that fails to load says why ---------------------------------------------------------


def test_a_csv_load_failure_shows_the_reason(monkeypatch):
    def source(_path):
        raise ValueError("names.csv is missing required column(s): Nickname")

    monkeypatch.setattr("clicknick.data.data_source.CsvDataSource", source)
    app, prompts = _app(monkeypatch)

    assert app._connection.load_csv("C:/tmp/names.csv") is False

    assert prompts == [
        ("showerror", "CSV Load Failed", "names.csv is missing required column(s): Nickname")
    ]


# -- app#2 / N3: the notice names what closes -------------------------------------------------


def test_project_change_over_csv_data_says_only_the_simulator_closes(monkeypatch):
    app, prompts = _app(monkeypatch)
    editor = _open(app, FakeStore(is_database=False, source_path="C:/tmp/Main_Address.csv"))
    app._session.simulator = object()
    notices = []
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **_kw: notices.append(args))

    app._connection._handle_project_change("CLICK Programming Software - Main2.ckp", "Main2.ckp")

    assert notices == [
        ("Project Changed", "The CLICK window now shows Main2.ckp. The Simulator will now close.")
    ]
    assert not editor.closed


def test_after_keep_open_editors_follow_the_new_project_and_its_build(monkeypatch):
    class FakeAddressEditor(FakeEditor):
        def __init__(self, _root, *, session, get_click_filename, get_analysis_service, **_kw):
            super().__init__()
            self.get_analysis_service = get_analysis_service
            self._get_click_filename = get_click_filename
            self.titles: list[str] = []
            session.register_editor(self)

        def refresh_title(self) -> None:
            self.titles.append(self._get_click_filename())

        def winfo_exists(self) -> bool:
            return True

    monkeypatch.setattr(
        "clicknick.views.address_editor.window.AddressEditorWindow", FakeAddressEditor
    )
    new_session = MagicMock(simulator=None, synced_pending=0)
    monkeypatch.setattr(
        "clicknick.connection_session.ConnectionSession",
        lambda click, **_kw: new_session.configure_mock(click=click) or new_session,
    )
    app, _prompts = _app(monkeypatch, yes_no=True)
    app.root.title = MagicMock()
    app._data = DataSession(FakeStore(is_database=True, unsaved=True))
    old_analysis = MagicMock()
    app._session.analysis = old_analysis
    app._open_address_editor()
    (editor,) = app._data.editors
    assert editor.get_analysis_service() is old_analysis

    app._connection._handle_project_change(
        "CLICK Programming Software - Renamed.ckp", "Renamed.ckp"
    )
    app._refresh_ui()  # Run the UI refresh that assigning _click schedules.

    assert app._data.editors == (editor,)
    assert editor.titles == ["Renamed.ckp"]
    assert editor.get_analysis_service() is new_session.analysis


def test_the_refresh_skips_editor_windows_that_are_gone(monkeypatch):
    import tkinter as tk

    class GoneEditor(FakeEditor):
        def winfo_exists(self) -> bool:
            return False

        def refresh_title(self) -> None:
            raise tk.TclError("application has been destroyed")

    app, _prompts = _app(monkeypatch)
    app.root.title = MagicMock()
    app._data = DataSession(FakeStore(is_database=True))
    app._data.register_editor(GoneEditor())

    app._refresh_ui()

    app.root.title.assert_called_once_with("ClickNick - Main.ckp - DB")


# -- T1: the Dataview Editor and Verify use the connected window's DataView folder ------------


class FakeDataviewWindow:
    """A stand-in for the window that _open_dataview_editor builds.

    It records the model that the window shows.
    """

    def __init__(self, _root, *, session, **_kw):
        self.shared_data = session.dataview
        self.closed = False
        self.unsaved = False
        session.register_dataview_window(self)
        self._session = session

    def has_unsaved_changes(self) -> bool:
        return self.unsaved

    def close_without_prompt(self) -> None:
        self.closed = True
        self._session.unregister_dataview_window(self)


def _two_click_folders(monkeypatch, tmp_path):
    """Make two CLICK temp folders, one for another window and one for the connected window.

    Return the connected window's DataView folder.
    """
    from clicknick.utils import click_temp

    monkeypatch.setattr(click_temp, "_windows_temp_path", lambda: str(tmp_path))
    (tmp_path / "CLICK (0001A2B4)" / "DataView").mkdir(parents=True)
    connected = tmp_path / f"CLICK ({222:08X})" / "DataView"
    connected.mkdir(parents=True)
    return connected


def test_the_dataview_editor_shows_the_connected_windows_folder(monkeypatch, tmp_path):
    connected = _two_click_folders(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "clicknick.views.dataview_editor.window.DataviewEditorWindow", FakeDataviewWindow
    )
    app, _prompts = _app(monkeypatch)
    app._apply_active_filter = MagicMock()
    app._data = DataSession(FakeStore(is_database=True))

    app._open_dataview_editor()

    assert app._data.dataview_window.shared_data.dataview_folder == connected


def test_with_no_window_the_dataview_editor_shows_the_csv_folder_or_none(monkeypatch, tmp_path):
    _two_click_folders(monkeypatch, tmp_path)
    app, _prompts = _app(monkeypatch)
    app._session = None
    app._data = DataSession(FakeStore(is_database=False, source_path=str(tmp_path / "a.csv")))
    assert app._dataview_folder() == tmp_path

    app._data = None
    assert app._dataview_folder() is None


def test_after_the_window_closes_a_csv_in_its_temp_folder_has_no_dataview_folder(
    monkeypatch, tmp_path
):
    """Open and Save As must not start in that folder, because CLICK deletes it."""
    _two_click_folders(monkeypatch, tmp_path)
    app, _prompts = _app(monkeypatch)
    app._session = None
    csv = tmp_path / f"CLICK ({222:08X})" / "Address.csv"
    app._data = DataSession(FakeStore(is_database=False, source_path=str(csv)))

    assert app._dataview_folder() is None


def test_verify_checks_the_connected_windows_dataview_folder(monkeypatch, tmp_path):
    connected = _two_click_folders(monkeypatch, tmp_path)
    checked = []

    def run_verification(_store, dataview_folder):
        checked.append(dataview_folder)
        return SimpleNamespace(passed=True, total_addresses=0, cdv_files_checked=0)

    monkeypatch.setattr("clicknick.utils.verification.run_verification", run_verification)
    app, _prompts = _app(monkeypatch)
    app._data = DataSession(FakeStore(is_database=True))

    app._verify_mdb_and_cdv()

    assert checked == [connected]


@pytest.mark.parametrize(
    ("action", "command"),
    [("_verify_mdb_and_cdv", "Verify MDB & CDV"), ("_clean_mdb", "Clean MDB")],
)
def test_database_repairs_refuse_csv_data(monkeypatch, action, command):
    """With a window connected and a CSV file loaded, neither command reads the CSV file."""
    read = []
    monkeypatch.setattr(
        "clicknick.utils.verification.run_verification", lambda *args: read.append(args)
    )
    monkeypatch.setattr(
        "clicknick.data.data_source.MdbDataSource", lambda **kwargs: read.append(kwargs)
    )
    app, prompts = _app(monkeypatch)
    app._data = DataSession(FakeStore(is_database=False, source_path="C:/tmp/Main_Address.csv"))

    getattr(app, action)()

    assert read == []
    assert prompts == []
    app._update_status.assert_called_once_with(
        f"⚠ {command} needs CLICK's database, and the nicknames loaded come from a CSV file. "
        "Select the window in the CLICK Windows list to load the database",
        "error",
    )


_READING = "ClickNick is still reading CLICK's database. Try again when it has finished"
_NOT_LOADED = (
    "ClickNick has not loaded CLICK's database for this project. Select the window in the "
    "CLICK Windows list to load it"
)
_DATABASE_OFF = "Database access is off, because CLICKNICK_DB_BACKEND is set to none (CSV mode)"
_OR_CSV = ", or use File > Load Nicknames from CSV"
_USE_CSV = ". Use File > Load Nicknames from CSV"


def _set_state(app: ClickNickApp, state: str) -> None:
    """Put *app* in *state*: no window, a window whose database is still loading or not loaded,
    or a window whose database is loaded but whose workspace build has not started.
    """
    if state == "no window":
        app._session = None
    elif state == "reading":
        app._session.begin_load()
    elif state == "not started":
        app._session.has_database = True


@pytest.mark.parametrize(
    "action",
    [
        "_open_dataview_editor",
        "_open_address_editor",
        "_repair_system_nicknames",
        "_upgrade_project",
    ],
)
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            "no window",
            "No nicknames loaded. Connect to a CLICK window, or use File > Load Nicknames from CSV",
        ),
        ("reading", f"⚠ {_READING}"),
        ("not loaded", f"⚠ {_NOT_LOADED}{_OR_CSV}"),
        ("access off", f"⚠ {_DATABASE_OFF}{_USE_CSV}"),
    ],
)
def test_without_nicknames_a_command_says_why(monkeypatch, action, state, expected):
    """With a window connected, no nicknames means that its database is loading or not loaded.

    Only with no window connected does the status say to connect. A CSV file is offered
    whenever the database cannot be loaded now.
    """
    if state == "access off":
        monkeypatch.setenv("CLICKNICK_DB_BACKEND", "none")
    app, prompts = _app(monkeypatch)
    _set_state(app, state)

    getattr(app, action)()

    app._update_status.assert_called_once_with(expected, "error")
    assert prompts == []


@pytest.mark.parametrize(
    ("action", "title", "lead"),
    [
        ("_run_program_checks", "Check Program", "Check Program needs the workspace."),
        ("_choose_program_checks", "Choose Checks", "Choose Checks needs the workspace."),
        ("_export_pyrung_project", "Export Workspace", "There is no workspace to export."),
    ],
)
@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("no window", "Connect to a CLICK window first."),
        ("reading", f"{_READING}."),
        ("not loaded", f"{_NOT_LOADED}."),
        (
            "not started",
            "ClickNick has not started building the workspace. Save the project in CLICK, then "
            "try again.",
        ),
    ],
)
def test_without_a_workspace_a_command_says_why(monkeypatch, action, title, lead, state, reason):
    """A command that needs the workspace says why there is none.

    It says to connect only when no window is connected.
    """
    app, _prompts = _app(monkeypatch)
    shown = []
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: shown.append(args))
    _set_state(app, state)

    if action == "_choose_program_checks":
        app._choose_program_checks(app.root, MagicMock())
    else:
        getattr(app, action)()

    assert shown == [(title, f"{lead}\n\n{reason}")]


def test_with_database_access_off_the_status_says_so(monkeypatch):
    """With CLICKNICK_DB_BACKEND set to none, selecting the window cannot load the database."""
    monkeypatch.setenv("CLICKNICK_DB_BACKEND", "none")
    app, _prompts = _app(monkeypatch)

    app._workspace.review_changes()
    app._data = DataSession(FakeStore(is_database=False, source_path="C:/tmp/Main_Address.csv"))
    app._clean_mdb()

    assert [call.args for call in app._update_status.call_args_list] == [
        (f"⚠ {_DATABASE_OFF}", "error"),
        (f"⚠ {_DATABASE_OFF}", "error"),
    ]


@pytest.mark.parametrize("keep", [True, False], ids=["keep", "discard"])
def test_project_change_asks_about_dataview_edits_over_csv_data(monkeypatch, keep):
    """Over CSV data, a project change asks the same question as over database data.

    The CSV data stays. The Dataview Editor shows the window's DataView folder, which then
    holds the other project's .cdv files.
    """
    app, prompts = _app(monkeypatch, yes_no=keep)
    store = FakeStore(is_database=False, unsaved=True, source_path="C:/tmp/Main_Address.csv")
    app._data = DataSession(store)
    dataview = FakeDataview()
    app._data.register_dataview_window(dataview)
    app._open_dataview_editor = MagicMock()

    app._connection._handle_project_change("CLICK Programming Software - Other.ckp", "Other.ckp")

    ((_, title, message),) = prompts
    assert title == "Project Changed"
    assert "unsaved Data View changes made in Main.ckp" in message
    assert "address changes" not in message  # CSV edits belong to the CSV file, not to the project.
    assert not dataview.saved
    assert app._data.store is store
    # The session follows the window to Other.ckp. It has no database, so nothing builds.
    assert app._session.click == ClickConnection("111", 222, "Other.ckp")
    assert not app._session.has_database
    if keep:
        assert not dataview.closed
        assert dataview.refreshed
        app._open_dataview_editor.assert_not_called()
    else:
        assert dataview.closed
        app._open_dataview_editor.assert_called_once_with()


def test_project_change_reopens_a_clean_dataview_editor_over_csv_data(monkeypatch):
    """With nothing to keep, the app opens the editor again on the window's DataView folder."""
    app, prompts = _app(monkeypatch)
    app._data = DataSession(FakeStore(is_database=False, source_path="C:/tmp/Main_Address.csv"))
    dataview = FakeDataview()
    dataview.has_unsaved_changes = lambda: False
    app._data.register_dataview_window(dataview)
    app._open_dataview_editor = MagicMock()

    app._connection._handle_project_change("CLICK Programming Software - Other.ckp", "Other.ckp")

    assert prompts == []
    assert dataview.closed
    assert not dataview.refreshed
    app._open_dataview_editor.assert_called_once_with()


def test_kept_database_edits_leave_the_dataview_editor_open_and_list_its_folder(monkeypatch):
    """A Save As keeps the folder, so the editor keeps its tabs and its Modbus connection."""
    monkeypatch.setattr(
        "clicknick.connection_session.ConnectionSession",
        lambda click, **_kw: MagicMock(click=click, simulator=None, synced_pending=0),
    )
    app, prompts = _app(monkeypatch, yes_no=True)
    app._data = DataSession(FakeStore(is_database=True, unsaved=True))
    dataview = FakeDataview()
    dataview.has_unsaved_changes = lambda: False
    app._data.register_dataview_window(dataview)
    app._open_dataview_editor = MagicMock()

    app._connection._handle_project_change(
        "CLICK Programming Software - Renamed.ckp", "Renamed.ckp"
    )

    assert [prompt[:2] for prompt in prompts] == [("askyesno", "Project Changed")]
    assert not dataview.closed
    assert dataview.refreshed
    app._open_dataview_editor.assert_not_called()


@pytest.mark.parametrize("commits", [True, False], ids=["commits", "will-not-commit"])
def test_project_change_counts_text_still_in_a_dataview_cell(monkeypatch, commits):
    """Over CSV data, text typed in a Dataview cell counts as an edit, so the app asks about it."""
    app, prompts = _app(monkeypatch, yes_no=False)
    app._data = DataSession(FakeStore(is_database=False, source_path="C:/tmp/Main_Address.csv"))
    dataview = FakeDataview()
    unsaved = []
    dataview.has_unsaved_changes = lambda: bool(unsaved)
    dataview.commit_open_cell_editor = lambda: unsaved.append(True) or True if commits else False
    app._data.register_dataview_window(dataview)
    app._open_dataview_editor = MagicMock()

    app._connection._handle_project_change("CLICK Programming Software - Other.ckp", "Other.ckp")

    ((_, title, message),) = prompts
    assert title == "Project Changed"
    assert "unsaved Data View changes" in message


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        ("failed", "Could not build the workspace: bad rung"),
        ("failed without a reason", "Could not build the workspace."),
        ("building", "ClickNick is still building the workspace. Try again when it finishes."),
    ],
)
@pytest.mark.parametrize("action", ["_choose_program_checks", "_run_program_checks"])
def test_workspace_commands_name_the_state_of_the_build(monkeypatch, action, build, reason):
    """With the database loaded, Choose Checks and Check Program say what happened to the build."""
    from clicknick.services.analysis_service import AnalysisService

    app, _prompts = _app(monkeypatch)
    shown = []
    for kind in ("showinfo", "showerror"):
        monkeypatch.setattr(
            f"tkinter.messagebox.{kind}",
            lambda *args, kind=kind, **kwargs: shown.append((kind, *args)),
        )
    session = app._session
    session.has_database = True
    session.analysis = AnalysisService()
    serves = session.analysis.mark_building()
    if build != "building":
        session.analysis.mark_failed("bad rung" if build == "failed" else "", serves=serves)

    if action == "_choose_program_checks":
        app._choose_program_checks(app.root, MagicMock())
        title = "Choose Checks"
    else:
        app._run_program_checks()
        title = "Check Program"

    kind = "showerror" if build.startswith("failed") and title == "Check Program" else "showinfo"
    assert shown == [(kind, title, f"{title} needs the workspace.\n\n{reason}")]


def test_check_program_says_where_the_checks_stop(monkeypatch):
    """Check Program names each rung that the built program holds as pyrung's undecoded()."""
    from pyrung import Bool, Program, out, rung
    from pyrung.click import undecoded

    from clicknick.services.analysis_service import (
        AnalysisResult,
        AnalysisService,
        undecoded_rungs_in,
    )

    with Program(strict=False) as program:
        with rung(Bool("Permit")):
            out(Bool("Enable"))
        with rung():
            undecoded("bad record", rung=1, stop="end")
    app, _prompts = _app(monkeypatch)
    app._session.analysis = AnalysisService()
    app._session.analysis._result = AnalysisResult(
        dataview=program.dataview(), program=program, undecoded=undecoded_rungs_in(program)
    )

    data = app._run_program_checks()

    assert data.stop_notes == (
        "ClickNick could not read rung 2 of Main Program. In Main Program, the checks cover only "
        "the rungs before it. To include the rest, click that rung's number in CLICK to select "
        "the rung. Then paste the rung again and save.",
    )


def test_check_program_names_the_rungs_of_the_program_that_it_checked(monkeypatch):
    """A build that finishes during the check does not change the rungs that the report names."""
    from pyrung import Program

    from clicknick.services.analysis_service import (
        AnalysisResult,
        AnalysisService,
        UndecodedRung,
    )

    program = Program(strict=False)
    app, _prompts = _app(monkeypatch)
    analysis = AnalysisService()
    app._session.analysis = analysis
    later = AnalysisResult(
        dataview=program.dataview(), program=program, undecoded=(UndecodedRung("Fill", 9),)
    )

    class _Program:
        def check(self, select):
            analysis._result = later
            return program.check(select=set())

    analysis._result = AnalysisResult(
        dataview=program.dataview(),
        program=_Program(),
        undecoded=(UndecodedRung("Main Program", 2),),
    )

    data = app._run_program_checks()

    assert len(data.stop_notes) == 1
    assert data.stop_notes[0].startswith("ClickNick could not read rung 2 of Main Program.")


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("bad rung", "Could not build the workspace: bad rung"),
        ("", "Could not build the workspace."),
    ],
)
def test_the_simulator_names_a_failed_build(monkeypatch, tmp_path, error, reason):
    """The Simulator says why the workspace is missing, the same as the other commands."""
    from clicknick.services.analysis_service import AnalysisService

    app, prompts = _app(monkeypatch)
    monkeypatch.setattr("clicknick.app.scr_files", lambda _folder: [tmp_path / "Scr1.tmp"])
    app._live_mdb_path = lambda: tmp_path / "SC_.mdb"
    app._start_analysis_build = MagicMock()
    session = app._session
    session.has_database = True
    session.analysis = AnalysisService()
    session.analysis.mark_failed(error)

    assert app._simulation_for_window("Cannot Simulate", "The simulation") is None

    assert prompts == [
        ("showerror", "Cannot Simulate", f"The simulation needs the workspace.\n\n{reason}")
    ]
