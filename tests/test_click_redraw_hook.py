"""Issue #36: after every Sync into CLICK's database, the connected CLICK window redraws.

The window redraws its nicknames. Tools > Redraw Nicknames in CLICK does the same by hand.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.app import ClickNickApp
from clicknick.connection_controller import ConnectionController
from clicknick.connection_session import ClickConnection, ConnectionSession
from clicknick.data.address_store import AddressStore
from clicknick.models.address_row import AddressRow
from clicknick.services import click_redraw
from clicknick.services.click_redraw import RedrawOutcome, RedrawResult
from clicknick.utils import win32_desktop

CLICK = ClickConnection("111", 222, "Main.ckp")
C1 = get_addr_key("C", 1)


class FakeRoot:
    """Records after() callbacks so a test can run them."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[int, object]] = []

    def after(self, delay, callback):
        self.scheduled.append((delay, callback))
        return f"after#{len(self.scheduled)}"

    def run(self, delay: int, limit: int = 1000) -> None:
        """Run the callbacks scheduled with *delay*, and those they schedule with it.

        Fail after *limit* callbacks. A callback that keeps rescheduling itself, such as a redraw
        whose result never comes, then fails the test instead of hanging it.
        """
        ran = 0
        while due := [entry for entry in self.scheduled if entry[0] == delay]:
            for entry in due:
                ran += 1
                if ran > limit:
                    pytest.fail(f"after({delay}) callbacks did not settle in {limit} runs")
                self.scheduled.remove(entry)
                entry[1]()


class DatabaseSource:
    """CLICK's database, as the store sees it."""

    supports_used_field = True
    is_database = True
    is_read_only = False
    file_path = ""  # There is nothing to monitor.

    def __init__(self) -> None:
        self.rows: dict[int, AddressRow] = {}
        self.fail = False

    def load_all_addresses(self):
        if self.fail:
            raise OSError("database locked")
        return dict(self.rows)

    def save_changes(self, rows):
        for row in rows:
            self.rows[row.addr_key] = AddressRow(
                memory_type=row.memory_type, address=row.address, nickname=row.nickname
            )
        return len(rows)


class CsvSource(DatabaseSource):
    supports_used_field = False
    is_database = False


def _app(click: ClickConnection | None = CLICK) -> ClickNickApp:
    app = ClickNickApp.__new__(ClickNickApp)
    app.__dict__["_ui_refresh_id"] = None
    app._request_ui_refresh = MagicMock()
    app.root = FakeRoot()
    app.settings = SimpleNamespace(redraw_on_sync=True)
    app._session = ConnectionSession(click) if click is not None else None
    app._data = None
    app._update_status = MagicMock()
    app.nickname_manager = SimpleNamespace(set_store=MagicMock())
    app._connection = ConnectionController(app)
    return app


def _store(source: DatabaseSource) -> AddressStore:
    store = AddressStore(source)
    store.load_initial_data()
    return store


def _rename(store: AddressStore, nickname: str = "Pump") -> None:
    with store.edit_session("Rename") as session:
        session.set_field(C1, "nickname", nickname)


# -- The Sync hook -----------------------------------------------------------------------


@pytest.fixture
def redraws(monkeypatch) -> MagicMock:
    redraw = MagicMock()
    monkeypatch.setattr(ConnectionController, "redraw_nicknames", redraw)
    return redraw


def test_a_sync_into_clicks_database_redraws_its_nicknames(redraws) -> None:
    app = _app()
    store = _store(DatabaseSource())
    app._open_data(store)
    _rename(store)

    store.save_all_changes()  # The Address Editor's Sync and Sync and Close

    redraws.assert_called_once_with(after_sync=True)


def test_yes_to_the_save_prompt_redraws_too(redraws, monkeypatch) -> None:
    monkeypatch.setattr("tkinter.messagebox.askyesnocancel", lambda *a, **k: True)
    app = _app()
    store = _store(DatabaseSource())
    app._open_data(store)
    _rename(store)

    assert app._close_data(prompt_save=True)

    redraws.assert_called_once_with(after_sync=True)


def test_a_failed_sync_redraws_nothing(redraws) -> None:
    app = _app()
    source = DatabaseSource()
    store = _store(source)
    app._open_data(store)
    _rename(store)
    source.fail = True

    with pytest.raises(OSError):
        store.save_all_changes()

    redraws.assert_not_called()


def test_a_csv_save_redraws_nothing(redraws) -> None:
    app = _app()
    store = _store(CsvSource())
    app._open_data(store)
    _rename(store)

    store.save_all_changes()

    redraws.assert_not_called()


def test_no_redraw_without_a_connected_window(redraws) -> None:
    app = _app(click=None)
    store = _store(DatabaseSource())
    app._open_data(store)
    _rename(store)

    store.save_all_changes()

    redraws.assert_not_called()


def test_with_redraw_ladder_on_sync_off_a_sync_says_how_to_redraw(redraws) -> None:
    app = _app()
    app.settings.redraw_on_sync = False
    store = _store(DatabaseSource())
    app._open_data(store)
    _rename(store)

    store.save_all_changes()

    redraws.assert_not_called()
    app._update_status.assert_called_once_with(
        "✓ Synced into CLICK's database. Use Tools > Redraw Nicknames in CLICK "
        "to show the new names in CLICK's ladder",
        "connected",
    )


# -- Running the redraw off the Tk thread ------------------------------------------------


class FakeSplash:
    """Records in *log* when the notice over CLICK's window shows and when it goes."""

    def __init__(self, log: list, click_hwnd: int) -> None:
        self.log = log
        log.append(("splash shown", click_hwnd))

    def close(self) -> None:
        self.log.append(("splash closed",))


@pytest.fixture
def desktop(monkeypatch) -> SimpleNamespace:
    """Return the result of each redraw run, in order, and the (pid, hwnd) each run was for.

    *log* lists what the redraw notice and the status line showed, in order.
    """
    found = SimpleNamespace(results=[], calls=[], threads=0, log=[])

    def redraw(_desktop, pid, main, *, own_pid):
        found.calls.append((pid, main))
        result = found.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def run_off_tk(work):
        found.threads += 1
        work()

    monkeypatch.setattr(click_redraw, "redraw_nicknames", redraw)
    monkeypatch.setattr(win32_desktop, "Win32ClickDesktop", lambda: object())
    monkeypatch.setattr(ConnectionController, "_run_off_tk", staticmethod(run_off_tk))
    monkeypatch.setattr(
        ConnectionController, "_show_splash", lambda _self, hwnd: FakeSplash(found.log, hwnd)
    )
    return found


def _status(app: ClickNickApp) -> tuple[str, str]:
    return app._update_status.call_args.args


def _logged_app(desktop: SimpleNamespace) -> ClickNickApp:
    """Return an app whose status lines go into *desktop.log*."""
    app = _app()
    app._update_status.side_effect = lambda message, style="normal": desktop.log.append(
        ("status", style)
    )
    return app


@pytest.mark.parametrize(
    ("result", "style"),
    [
        (RedrawResult(RedrawOutcome.REFRESHED), "connected"),
        (RedrawResult(RedrawOutcome.BUSY, "CLICK does not answer"), "error"),
        (RedrawResult(RedrawOutcome.FAILED, 'CLICK showed "Open"'), "error"),
        (OSError("access denied"), "error"),
    ],
    ids=["refreshed", "busy", "failed", "raised"],
)
def test_the_notice_shows_while_the_redraw_runs_and_goes_before_the_status(
    desktop, result, style
) -> None:
    app = _logged_app(desktop)
    desktop.results.append(result)

    app._connection.redraw_nicknames(after_sync=True)
    app.root.run(100)

    assert desktop.log == [("splash shown", 222), ("splash closed",), ("status", style)]


def test_the_notice_goes_when_the_redraw_ends_on_another_window(desktop, monkeypatch) -> None:
    app = _logged_app(desktop)
    running = []
    monkeypatch.setattr(ConnectionController, "_run_off_tk", staticmethod(running.append))
    desktop.results.append(RedrawResult(RedrawOutcome.FAILED, "CLICK's window is closed"))

    app._connection.redraw_nicknames(after_sync=True)
    assert desktop.log == [("splash shown", 222)]
    app._session = ConnectionSession(ClickConnection("333", 444, "Other.ckp"))
    running.pop()()
    app.root.run(100)

    assert desktop.log == [("splash shown", 222), ("splash closed",)]


def test_the_notice_goes_when_the_redraw_cannot_start(desktop, monkeypatch) -> None:
    app = _logged_app(desktop)

    def no_thread(_work):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(ConnectionController, "_run_off_tk", staticmethod(no_thread))

    with pytest.raises(RuntimeError):
        app._connection.redraw_nicknames(after_sync=True)

    assert desktop.log == [("splash shown", 222), ("splash closed",)]
    assert not app._connection._redraw_running


def test_the_redraw_runs_when_the_notice_cannot_show(monkeypatch) -> None:
    from clicknick.views import redraw_splash

    refreshed = RedrawResult(RedrawOutcome.REFRESHED)
    monkeypatch.setattr(click_redraw, "redraw_nicknames", lambda *_a, **_k: refreshed)
    monkeypatch.setattr(win32_desktop, "Win32ClickDesktop", lambda: object())
    monkeypatch.setattr(ConnectionController, "_run_off_tk", staticmethod(lambda work: work()))

    def no_display(_root, _hwnd):
        raise RuntimeError("no display")

    monkeypatch.setattr(redraw_splash, "RedrawSplash", no_display)
    app = _app()

    app._connection.redraw_nicknames(after_sync=False)
    app.root.run(100)

    assert _status(app) == ("✓ CLICK shows the nicknames from its database", "connected")


def test_the_redraw_runs_when_the_notice_module_cannot_load(monkeypatch) -> None:
    """A redraw that stopped before it ran would leave every later request waiting."""
    refreshed = RedrawResult(RedrawOutcome.REFRESHED)
    monkeypatch.setattr(click_redraw, "redraw_nicknames", lambda *_a, **_k: refreshed)
    monkeypatch.setattr(win32_desktop, "Win32ClickDesktop", lambda: object())
    monkeypatch.setattr(ConnectionController, "_run_off_tk", staticmethod(lambda work: work()))
    monkeypatch.setitem(sys.modules, "clicknick.views.redraw_splash", None)  # Import fails
    app = _app()

    app._connection.redraw_nicknames(after_sync=False)
    app.root.run(100)

    assert _status(app) == ("✓ CLICK shows the nicknames from its database", "connected")
    assert not app._connection._redraw_running


def test_the_menu_command_redraws_with_redraw_ladder_on_sync_off(desktop) -> None:
    app = _app()
    app.settings.redraw_on_sync = False
    desktop.results.append(RedrawResult(RedrawOutcome.REFRESHED))

    app._connection.redraw_nicknames(after_sync=False)
    app.root.run(100)

    assert desktop.calls == [(111, 222)]
    assert _status(app) == ("✓ CLICK shows the nicknames from its database", "connected")


def test_a_redraw_reports_click_shows_the_names(desktop) -> None:
    app = _app()
    desktop.results.append(RedrawResult(RedrawOutcome.REFRESHED))

    app._connection.redraw_nicknames(after_sync=True)
    app.root.run(100)

    assert desktop.calls == [(111, 222)]
    assert _status(app) == ("✓ CLICK shows the nicknames from its database", "connected")


def test_a_busy_click_after_sync_says_the_names_are_synced_and_how_to_redraw(desktop) -> None:
    app = _app()
    desktop.results.append(RedrawResult(RedrawOutcome.BUSY, 'CLICK shows "Out"'))

    app._connection.redraw_nicknames(after_sync=True)
    app.root.run(100)

    message, style = _status(app)
    assert style == "error"
    assert message == (
        '⚠ Synced into CLICK\'s database, but CLICK was busy (CLICK shows "Out"). '
        "Use Tools > Redraw Nicknames in CLICK to show them"
    )


def test_a_failed_redraw_after_sync_says_so(desktop) -> None:
    app = _app()
    desktop.results.append(OSError("access denied"))

    app._connection.redraw_nicknames(after_sync=True)
    app.root.run(100)

    message, style = _status(app)
    assert style == "error"
    assert message.startswith("⚠ Synced into CLICK's database, but CLICK did not redraw them")
    assert "(access denied)" in message


def test_the_menu_command_on_a_busy_click_says_to_close_its_dialog(desktop) -> None:
    app = _app()
    desktop.results.append(RedrawResult(RedrawOutcome.BUSY, "CLICK's window is disabled"))

    app._connection.redraw_nicknames(after_sync=False)
    app.root.run(100)

    assert _status(app) == (
        "⚠ CLICK is busy (CLICK's window is disabled). Close its dialog and try again",
        "error",
    )


def test_requests_while_a_redraw_runs_run_once_after_it(desktop) -> None:
    app = _app()
    desktop.results += [
        RedrawResult(RedrawOutcome.REFRESHED),
        RedrawResult(RedrawOutcome.BUSY, "CLICK does not answer"),
    ]

    app._connection.redraw_nicknames(after_sync=False)
    app._connection.redraw_nicknames(after_sync=True)  # A Sync while the first runs
    app._connection.redraw_nicknames(after_sync=False)
    assert desktop.threads == 1
    app.root.run(100)

    assert desktop.threads == 2
    assert desktop.results == []
    # The second run counts as after a Sync, because one of the requests it serves was one.
    message, _style = _status(app)
    assert message.startswith("⚠ Synced into CLICK's database, but CLICK was busy")


def test_a_redraw_that_ends_on_another_window_shows_nothing(desktop, monkeypatch) -> None:
    app = _app()
    running = []
    monkeypatch.setattr(ConnectionController, "_run_off_tk", staticmethod(running.append))
    desktop.results += [
        RedrawResult(RedrawOutcome.FAILED, "CLICK's window is closed or hidden"),
        RedrawResult(RedrawOutcome.REFRESHED),
    ]

    app._connection.redraw_nicknames(after_sync=True)
    app._connection.redraw_nicknames(after_sync=False)  # This request is in the same session.
    app._session = ConnectionSession(ClickConnection("333", 444, "Other.ckp"))
    running.pop()()  # CLICK's window closed, so the redraw ends with another window connected.
    app.root.run(100)

    app._update_status.assert_not_called()
    assert running == []  # The request for the closed window does not run.
    assert desktop.calls == [(111, 222)]

    app._connection.redraw_nicknames(after_sync=False)  # The new window's own request runs.
    running.pop()()
    app.root.run(100)

    assert desktop.calls == [(111, 222), (333, 444)]
    assert _status(app) == ("✓ CLICK shows the nicknames from its database", "connected")


def test_a_redraw_reports_on_a_new_session_of_the_same_window(desktop, monkeypatch) -> None:
    """A Save As that keeps the edits opens a new session on the same CLICK window."""
    app = _app()
    running = []
    monkeypatch.setattr(ConnectionController, "_run_off_tk", staticmethod(running.append))
    desktop.results += [
        RedrawResult(RedrawOutcome.REFRESHED),
        RedrawResult(RedrawOutcome.BUSY, "CLICK does not answer"),
    ]

    app._connection.redraw_nicknames(after_sync=False)
    app._connection.redraw_nicknames(after_sync=True)  # A Sync while the first runs
    app._session = ConnectionSession(ClickConnection("111", 222, "Copy.ckp"))
    first = running.pop()
    # The Sync's request then runs on the new session at once.
    monkeypatch.setattr(ConnectionController, "_run_off_tk", staticmethod(lambda work: work()))
    first()
    app.root.run(100)

    assert desktop.calls == [(111, 222), (111, 222)]
    shown = [call.args for call in app._update_status.call_args_list]
    assert shown[0] == ("✓ CLICK shows the nicknames from its database", "connected")
    assert shown[1][0].startswith("⚠ Synced into CLICK's database, but CLICK was busy")
    assert len(shown) == 2


def test_the_menu_command_needs_a_connected_window(desktop) -> None:
    app = _app(click=None)

    app._connection.redraw_nicknames(after_sync=False)

    assert desktop.threads == 0
    assert _status(app) == ("⚠ Connect to a CLICK window first", "error")


# -- The menu entry ----------------------------------------------------------------------


@pytest.mark.parametrize(("click", "state"), [(CLICK, "normal"), (None, "disabled")])
def test_the_menu_entry_is_enabled_only_while_a_window_is_connected(click, state) -> None:
    app = _app(click)
    app.root = MagicMock()
    app.tools_menu = MagicMock()
    app._tools_redraw_index = 5

    app._refresh_ui()

    app.tools_menu.entryconfigure.assert_called_once_with(5, state=state)
