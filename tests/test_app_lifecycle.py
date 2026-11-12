"""App lifecycle: closing ClickNick, CLICK closing or changing project, connecting, CSV loads."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.connection_session import ClickConnection
from clicknick.data_session import DataSession
from clicknick.detection.window_detector import ClickInstance


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


def _app(monkeypatch, *, answer=None, yes_no=False) -> tuple[ClickNickApp, list]:
    """A ClickNickApp without Tk, connected to Main.ckp, monitoring off.

    *answer* answers Yes/No/Cancel questions, *yes_no* Yes/No ones.
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
    monkeypatch.setattr(
        "tkinter.messagebox.showerror",
        lambda *args, **kwargs: prompts.append(("showerror", *args[:2])),
    )
    app = ClickNickApp.__new__(ClickNickApp)
    app.__dict__["_ui_refresh_id"] = None
    app._request_ui_refresh = MagicMock()
    app.root = FakeRoot()
    app._session = None
    app._data = None
    app._connection_probe_token = None
    app._update_status = MagicMock()
    app.monitoring = False
    app.monitor_task_id = None
    app._watch_running = False
    app._status_after_id = None
    app.overlay = None
    app._live_server = None
    app.start_button = MagicMock()
    app.nickname_manager = SimpleNamespace(set_store=MagicMock(), has_database_backend=lambda: True)
    app.click_instances = [_instance("111", 222, "Main.ckp")]
    app.instances_combobox = {}
    app.selected_instance_var = FakeVar("Main.ckp")
    app._click = ClickConnection("111", 222, "Main.ckp")
    app._load_workspace_pairing = MagicMock()
    app._reset_workspace_pairing = MagicMock()
    app._workspace_config = None
    app._load_instance_database = MagicMock()
    app._remove_stale_compare_copies = MagicMock()
    app.detector = SimpleNamespace(
        check_window_exists=lambda _pid: True,
        get_window_title=lambda hwnd: next(
            (instance.title for instance in app.click_instances if instance.hwnd == hwnd), ""
        ),
        get_click_instances=lambda: list(app.click_instances),
        detect_child_window=MagicMock(return_value=None),
    )
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
    session = SimpleNamespace(close=MagicMock(), simulator=None)
    app._session = session

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
        ("Unsaved Changes", "You have unsaved changes in Dataview Editor. Save before closing?")
    ]
    assert dataview.saved and dataview.closed
    assert app.root.destroy.called


# -- app#2: a project change keeps CSV data ---------------------------------------------------


def test_project_change_keeps_csv_data_with_unsaved_edits(monkeypatch):
    app, prompts = _app(monkeypatch)
    store = FakeStore(is_database=False, unsaved=True, source_path="C:/Users/me/Main_Address.csv")
    editor = _open(app, store)
    app.monitoring = True
    session = SimpleNamespace(close=MagicMock(), simulator=None)
    app._session = session

    app._handle_project_change("CLICK Programming Software - Main2.ckp", "Main2.ckp")

    assert prompts == []
    assert app._data.store is store
    assert not editor.closed
    store.stop_file_monitoring.assert_not_called()
    assert not store.save_all_changes.called
    assert app._csv_path == "C:/Users/me/Main_Address.csv"
    assert app._click == ClickConnection("111", 222, "Main2.ckp")
    assert app.selected_instance_var.get() == "Main2.ckp"
    assert app.monitoring
    session.close.assert_called_once()
    app._load_instance_database.assert_not_called()


def test_project_change_closes_database_data_and_loads_the_new_project(monkeypatch):
    app, prompts = _app(monkeypatch)
    editor = _open(app, FakeStore(is_database=True))

    app._handle_project_change("CLICK Programming Software - Main2.ckp", "Main2.ckp")

    assert prompts == [("Project Changed",)]
    assert editor.closed
    assert app._data is None
    app._load_instance_database.assert_called_once_with("111", "Main2.ckp", 222)


# -- app#11: a project change asks about unsaved database edits ---------------------------------


def test_project_change_can_keep_unsaved_database_edits_for_the_new_project(monkeypatch):
    sessions = []
    monkeypatch.setattr(
        "clicknick.connection_session.ConnectionSession",
        lambda click, **_kw: sessions.append(click) or MagicMock(simulator=None, synced_pending=0),
    )
    app, prompts = _app(monkeypatch, yes_no=True)
    store = FakeStore(is_database=True, unsaved=True)
    editor = _open(app, store)
    old_session = SimpleNamespace(close=MagicMock(), simulator=None)
    app._session = old_session

    app._handle_project_change("CLICK Programming Software - Renamed.ckp", "Renamed.ckp")

    ((_, title, message),) = prompts
    assert title == "Project Changed"
    assert "Keep them as unsaved changes for Renamed.ckp?" in message
    assert app._data.store is store
    assert not editor.closed
    store.stop_file_monitoring.assert_not_called()  # It reads the base from the new database
    assert not store.save_all_changes.called
    app._load_instance_database.assert_not_called()
    old_session.close.assert_called_once()
    assert sessions == [ClickConnection("111", 222, "Renamed.ckp")]
    app._session.start_analysis.assert_called_once_with(app.root)
    assert app._click == ClickConnection("111", 222, "Renamed.ckp")
    assert app._window_title() == "ClickNick - Renamed.ckp - DB"


def test_project_change_can_discard_unsaved_database_edits(monkeypatch):
    app, prompts = _app(monkeypatch, yes_no=False)
    store = FakeStore(is_database=True, unsaved=True)
    editor = _open(app, store)

    app._handle_project_change("CLICK Programming Software - Other.ckp", "Other.ckp")

    assert [prompt[:2] for prompt in prompts] == [
        ("askyesno", "Project Changed"),
        ("Project Changed",),
    ]
    assert editor.closed
    assert not store.save_all_changes.called
    assert app._data is None
    app._load_instance_database.assert_called_once_with("111", "Other.ckp", 222)


def test_project_change_counts_text_still_in_a_cell_editor(monkeypatch):
    app, prompts = _app(monkeypatch, yes_no=True)
    store = FakeStore(is_database=True)
    editor = _open(app, store)
    editor.commit_open_cell_editor = lambda: setattr(store, "_unsaved", True) or True

    app._handle_project_change("CLICK Programming Software - Renamed.ckp", "Renamed.ckp")

    assert [prompt[:2] for prompt in prompts] == [("askyesno", "Project Changed")]
    assert app._data.store is store


@pytest.mark.parametrize("save", [True, False], ids=["save", "dont-save"])
def test_project_change_offers_to_save_dataview_edits(monkeypatch, save):
    app, prompts = _app(monkeypatch, yes_no=save)
    app._data = DataSession(FakeStore(is_database=True))
    dataview = FakeDataview()
    app._data.register_dataview_window(dataview)

    app._handle_project_change("CLICK Programming Software - Other.ckp", "Other.ckp")

    assert prompts == [
        ("Project Changed",),
        (
            "askyesno",
            "Unsaved Changes",
            "You have unsaved changes in Dataview Editor. Save before closing?",
        ),
    ]
    assert dataview.saved is save
    assert dataview.closed
    assert app._data is None
    app._load_instance_database.assert_called_once_with("111", "Other.ckp", 222)


# -- The window list always shows the connected window --------------------------------------------


def test_connecting_by_itself_selects_the_window_in_the_list(monkeypatch):
    monkeypatch.setattr("clicknick.utils.mdb_shared.get_database_backend", lambda: "odbc")
    app, _prompts = _app(monkeypatch)
    app._click = None
    app.selected_instance_var = FakeVar("")

    app.refresh_click_instances()

    assert app._click == ClickConnection("111", 222, "Main.ckp")
    assert app.instances_combobox["values"] == ["Main.ckp"]
    assert app.selected_instance_var.get() == "Main.ckp"


def test_a_project_change_lists_a_window_the_list_left_out(monkeypatch):
    app, _prompts = _app(monkeypatch)
    _open(app, FakeStore(is_database=False))
    # Read while the window's title showed no project
    app.detector.get_click_instances = lambda: []
    app.refresh_click_instances()
    assert app.instances_combobox["values"] == ["Main.ckp"]

    app._handle_project_change("CLICK Programming Software - follow.ckp", "follow.ckp")

    assert app.instances_combobox["values"] == ["follow.ckp"]
    assert app.selected_instance_var.get() == "follow.ckp"
    (listed,) = app.click_instances
    assert listed == ClickInstance(
        "111", "CLICK Programming Software - follow.ckp", "follow.ckp", 222
    )
    app.selected_instance_var.set("follow.ckp")
    app.connect_to_instance = MagicMock()
    app._on_instance_selected()
    app.connect_to_instance.assert_called_once()


# -- app#3: the CSV path is the open data's -----------------------------------------------------


def _patch_csv(monkeypatch, *, fails: bool = False) -> None:
    def source(path):
        if fails:
            raise ValueError("bad csv")
        return SimpleNamespace(path=path)

    monkeypatch.setattr("clicknick.data.data_source.CsvDataSource", source)
    monkeypatch.setattr(
        "clicknick.app.AddressStore",
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

    # A CLICK Save As then reloads the database for the new name
    app._handle_project_change("CLICK Programming Software - Renamed.ckp", "Renamed.ckp")
    app._load_instance_database.assert_called_once_with("111", "Renamed.ckp", 222)


def test_a_csv_load_sets_the_csv_path_with_the_data(monkeypatch):
    _patch_csv(monkeypatch)
    app, _prompts = _app(monkeypatch)

    assert app.load_csv("C:/tmp/Other.csv")

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
    app.connect_to_instance = MagicMock()
    other = _instance("333", 444, "Other.ckp")
    app.detector.get_click_instances = lambda: [other]

    app._handle_window_closed()
    (refresh,) = app.root.take(2000)
    refresh()

    app.connect_to_instance.assert_not_called()
    assert app.instances_combobox["values"] == ["Other.ckp"]
    assert app.selected_instance_var.get() == ""
    assert app._data.store is store
    assert not editor.closed


def test_refresh_with_nothing_loaded_connects_to_the_first_window(monkeypatch):
    app, _prompts = _app(monkeypatch)
    app._click = None
    app.connect_to_instance = MagicMock()
    other = _instance("333", 444, "Other.ckp")
    app.detector.get_click_instances = lambda: [other]

    app.refresh_click_instances()

    app.connect_to_instance.assert_called_once_with("333", other.title, "Other.ckp", 444)


# -- app#5: Stop turns off popups only -----------------------------------------------------------


def test_stopped_monitoring_still_notices_click_closing(monkeypatch):
    app, _prompts = _app(monkeypatch)
    editor = _open(app, FakeStore(is_database=True, unsaved=True))
    session = SimpleNamespace(close=MagicMock(), simulator=None)
    app._session = session
    app.refresh_click_instances = MagicMock()

    app.button_start_monitoring()
    app.stop_monitoring()
    app.detector.check_window_exists = lambda _pid: False
    for tick in app.root.take(100):
        tick()

    session.close.assert_called_once()
    assert editor.closed
    assert app._click is None
    assert app.root.pending(100) == 0
    assert not app._watch_running


def test_stopped_monitoring_still_notices_a_project_change(monkeypatch):
    app, _prompts = _app(monkeypatch)
    _open(app, FakeStore(is_database=True))
    app.detector.get_window_title = lambda _hwnd: "CLICK Programming Software - Next.ckp"

    app._watch_connection()

    app._load_instance_database.assert_called_once_with("111", "Next.ckp", 222)
    app.detector.detect_child_window.assert_not_called()
    assert app.root.pending(100) == 1


def test_popup_detection_runs_only_while_monitoring(monkeypatch):
    app, _prompts = _app(monkeypatch)
    _open(app, FakeStore(is_database=True))

    app.button_start_monitoring()
    app.detector.detect_child_window.assert_called_once_with("111")
    app.stop_monitoring()
    (tick,) = app.root.take(100)
    tick()

    app.detector.detect_child_window.assert_called_once_with("111")
    assert app.root.pending(100) == 1


def test_connecting_starts_the_watch_before_data_loads(monkeypatch):
    monkeypatch.setattr("clicknick.utils.mdb_shared.get_database_backend", lambda: "odbc")
    app, _prompts = _app(monkeypatch)
    app._click = None

    app.connect_to_instance("111", "CLICK Programming Software - Main.ckp", "Main.ckp", 222)
    app.connect_to_instance("111", "CLICK Programming Software - Main.ckp", "Main.ckp", 222)

    assert app._watch_running
    assert app.root.pending(100) == 1


@pytest.mark.parametrize("process_alive", [False, True], ids=["gone", "alive"])
def test_refresh_closes_a_missing_window_only_when_its_process_is_gone(monkeypatch, process_alive):
    app, prompts = _app(monkeypatch)
    store = FakeStore(is_database=True, unsaved=True)
    editor = _open(app, store)
    session = SimpleNamespace(close=MagicMock(), simulator=None)
    app._session = session
    # The list leaves out a window whose title shows no project, or is empty on an error
    app.detector.get_click_instances = lambda: []
    app.detector.check_window_exists = lambda _pid: process_alive

    app.refresh_click_instances()

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
    app._click = None
    app.connect_to_instance = MagicMock()
    first, second = _instance("1", 0x10, "Main.ckp"), _instance("2", 0x20, "Main.ckp")
    app.detector.get_click_instances = lambda: [first, second]
    app._data = DataSession(FakeStore(is_database=False))  # nothing auto-connects
    app.refresh_click_instances()

    labels = app.instances_combobox["values"]
    assert labels == ["Main.ckp (PID 1)", "Main.ckp (PID 2)"]
    app.selected_instance_var.set(labels[1])
    app._on_instance_selected()

    app.connect_to_instance.assert_called_once_with(
        "2", second.title, "Main.ckp", 0x20, user_picked=True
    )


def test_cancelling_a_switch_shows_the_connected_window_again(monkeypatch):
    app, prompts = _app(monkeypatch, answer=None)
    store = FakeStore(is_database=False, unsaved=True)
    _open(app, store)
    other = _instance("333", 444, "Other.ckp")
    app.click_instances.append(other)
    app.selected_instance_var.set("Other.ckp")

    app.connect_to_instance("333", other.title, "Other.ckp", 444)

    assert len(prompts) == 1
    assert app._data.store is store
    assert app._click == ClickConnection("111", 222, "Main.ckp")
    assert app.selected_instance_var.get() == "Main.ckp"


# -- app#9: the delayed Monitoring status ---------------------------------------------------------


def test_delayed_monitoring_status_does_not_overwrite_a_later_one(monkeypatch):
    app, _prompts = _app(monkeypatch)
    app.refresh_click_instances = MagicMock()
    app.monitoring = True

    app._on_data_ready()
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
    assert app.monitoring is False
    assert app.start_button.configure.call_args.kwargs == {"text": "▶ Start"}
    assert app.root.pending(1000) == 0


def _stopped_app(monkeypatch, *, answer=None) -> tuple[ClickNickApp, list]:
    app, prompts = _app(monkeypatch, answer=answer)
    app.monitoring = True
    app.stop_monitoring()
    return app, prompts


def test_stop_sticks_through_a_project_change(monkeypatch):
    app, _prompts = _stopped_app(monkeypatch)
    _open(app, FakeStore(is_database=True))
    app.detector.get_window_title = lambda _hwnd: "CLICK Programming Software - Next.ckp"

    app._watch_connection()
    app._load_instance_database.assert_called_once_with("111", "Next.ckp", 222)
    # What the off-thread load does once the new database is read
    app._open_data(FakeStore(is_database=True))
    assert app.load_from_database()

    _assert_stopped(app)


def test_stop_sticks_through_the_csv_fallback(monkeypatch):
    _patch_csv(monkeypatch)
    app, _prompts = _stopped_app(monkeypatch)
    app._show_main_window = MagicMock()
    monkeypatch.setattr("clicknick.app.find_fallback_csv", lambda _hwnd: "Address.csv")
    dialog = MagicMock()
    dialog.return_value.show.return_value = "C:/tmp/Main_Address.csv"
    monkeypatch.setattr("clicknick.app.CsvFallbackDialog", dialog)

    app._connect_csv_fallback("Main.ckp", 222)

    assert app._csv_path == "C:/tmp/Main_Address.csv"
    _assert_stopped(app)


def test_no_csv_chosen_says_nothing_is_loaded_without_saying_stopped(monkeypatch):
    app, _prompts = _app(monkeypatch)
    app.monitoring = True
    app._odbc_warning_shown = True
    app._show_main_window = MagicMock()
    monkeypatch.setattr("clicknick.app.find_fallback_csv", lambda _hwnd: None)

    app._connect_csv_fallback("Main.ckp", 222)

    app._update_status.assert_called_once_with(
        "No nicknames loaded - use File → Load Nicknames...", "error"
    )
    assert app.monitoring is True


def test_stop_sticks_when_a_refresh_connects_after_the_window_closed(monkeypatch):
    monkeypatch.setattr("clicknick.utils.mdb_shared.get_database_backend", lambda: "odbc")
    app, _prompts = _stopped_app(monkeypatch)
    _open(app, FakeStore(is_database=True))
    other = _instance("333", 444, "Other.ckp")
    app.detector.check_window_exists = lambda pid: pid == "333"
    app.detector.get_click_instances = lambda: [other]

    app._watch_connection()
    assert app._click is None and app._data is None
    (refresh,) = app.root.take(2000)
    refresh()
    app._load_instance_database.assert_called_once_with("333", "Other.ckp", 444)
    app._open_data(FakeStore(is_database=True))
    app.load_from_database()

    assert app._click == ClickConnection("333", 444, "Other.ckp")
    _assert_stopped(app)


def test_picking_a_window_turns_monitoring_on(monkeypatch):
    monkeypatch.setattr("clicknick.utils.mdb_shared.get_database_backend", lambda: "odbc")
    app, _prompts = _stopped_app(monkeypatch)
    other = _instance("333", 444, "Other.ckp")
    app.click_instances.append(other)
    app.selected_instance_var.set("Other.ckp")

    app._on_instance_selected()

    assert app.monitoring is True
    assert app.start_button.configure.call_args.kwargs == {"text": "⏹ Stop"}


# -- A CSV that fails to load says why ---------------------------------------------------------


def test_a_csv_load_failure_shows_the_reason(monkeypatch):
    def source(_path):
        raise ValueError("names.csv has no Nickname column")

    monkeypatch.setattr("clicknick.data.data_source.CsvDataSource", source)
    app, prompts = _app(monkeypatch)

    assert app.load_csv("C:/tmp/names.csv") is False

    assert prompts == [("showerror", "CSV Load Failed", "names.csv has no Nickname column")]


# -- app#2 / N3: the notice names what closes -------------------------------------------------


def test_project_change_over_csv_data_says_only_the_simulator_closes(monkeypatch):
    app, prompts = _app(monkeypatch)
    editor = _open(app, FakeStore(is_database=False, source_path="C:/tmp/Main_Address.csv"))
    app._session = SimpleNamespace(close=MagicMock(), simulator=object())
    notices = []
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **_kw: notices.append(args))

    app._handle_project_change("CLICK Programming Software - Main2.ckp", "Main2.ckp")

    assert notices == [
        ("Project Changed", "The Click project was changed. The Simulator will now close.")
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

    monkeypatch.setattr(
        "clicknick.views.address_editor.window.AddressEditorWindow", FakeAddressEditor
    )
    new_session = MagicMock(simulator=None, synced_pending=0)
    monkeypatch.setattr(
        "clicknick.connection_session.ConnectionSession", lambda _click, **_kw: new_session
    )
    app, _prompts = _app(monkeypatch, yes_no=True)
    app.root.title = MagicMock()
    app._data = DataSession(FakeStore(is_database=True, unsaved=True))
    old_analysis = object()
    app._session = SimpleNamespace(close=MagicMock(), simulator=None, analysis=old_analysis)
    app._open_address_editor()
    (editor,) = app._data.editors
    assert editor.get_analysis_service() is old_analysis

    app._handle_project_change("CLICK Programming Software - Renamed.ckp", "Renamed.ckp")
    app._refresh_ui()  # What assigning _click schedules

    assert app._data.editors == (editor,)
    assert editor.titles == ["Renamed.ckp"]
    assert editor.get_analysis_service() is new_session.analysis
