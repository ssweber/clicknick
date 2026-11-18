"""Issue #36: after a Sync into CLICK's database, the connected CLICK window redraws.

The window redraws its nicknames. After the first redraw, a notice explains it, once for
each Windows user. Tools > Redraw Nicknames in CLICK redraws by hand and shows no notice.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.app import ClickNickApp
from clicknick.config import AppSettings
from clicknick.connection_controller import REDRAW_NOTICE, ConnectionController
from clicknick.connection_session import ClickConnection, ConnectionSession
from clicknick.data.address_store import AddressStore
from clicknick.models.address_row import AddressRow
from clicknick.services import click_redraw
from clicknick.services.click_redraw import RedrawOutcome, RedrawResult
from clicknick.services.settings_file import SavedSettings, read_settings, write_settings
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


class FakeSettings:
    """AppSettings' Redraw Ladder on Sync, without Tk. The notice has already shown."""

    def __init__(self, redraw_on_sync: bool = True) -> None:
        self.redraw_on_sync = redraw_on_sync
        self.redraw_notice_due = False


def _app(click: ClickConnection | None = CLICK) -> ClickNickApp:
    app = ClickNickApp.__new__(ClickNickApp)
    app.__dict__["_ui_refresh_id"] = None
    app._request_ui_refresh = MagicMock()
    app.root = FakeRoot()
    app.settings = FakeSettings()
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


# -- The notice after the first redraw ---------------------------------------------------


@pytest.fixture
def notices(monkeypatch) -> list:
    """Return the title and text of each notice that ClickNick shows."""
    shown: list = []
    monkeypatch.setattr(
        "clicknick.connection_controller.messagebox.showinfo",
        lambda title, message, **_kwargs: shown.append((title, message)),
    )
    return shown


@pytest.fixture
def fresh(tk_root, tmp_path, desktop) -> SimpleNamespace:
    """Return an app with real AppSettings, read from a settings file that does not exist."""
    path = tmp_path / "settings.json"
    app = _app()
    app.settings = AppSettings(path)
    store = _store(DatabaseSource())
    app._open_data(store)
    return SimpleNamespace(app=app, store=store, path=path, desktop=desktop)


def _sync(fresh: SimpleNamespace, nickname: str, result=None) -> None:
    """Rename C1 and Sync. A redraw that runs ends with *result* (REFRESHED)."""
    fresh.desktop.results.append(result or RedrawResult(RedrawOutcome.REFRESHED))
    _rename(fresh.store, nickname)
    fresh.store.save_all_changes()
    fresh.app.root.run(100)


def test_the_first_redraw_after_a_sync_shows_the_notice_once(notices, fresh) -> None:
    _sync(fresh, "Pump")
    _sync(fresh, "Valve")

    assert fresh.desktop.calls == [(111, 222), (111, 222)]
    assert notices == [("Redraw Ladder on Sync", REDRAW_NOTICE)]
    assert read_settings(fresh.path) == SavedSettings(redraw_notice_shown=True)
    # The next start reads the file and shows no notice.
    again = AppSettings(fresh.path)
    assert not again.redraw_notice_due
    assert again.redraw_on_sync


def test_the_notice_waits_for_a_redraw_that_shows_the_names(notices, fresh) -> None:
    _sync(fresh, "Pump", result=RedrawResult(RedrawOutcome.BUSY, "CLICK does not answer"))
    assert notices == []

    _sync(fresh, "Valve")

    assert len(notices) == 1


def test_a_sync_that_writes_nothing_shows_no_notice(notices, fresh) -> None:
    fresh.store.save_all_changes()  # No edits

    assert fresh.desktop.calls == []
    assert notices == []
    assert fresh.app.settings.redraw_notice_due
    assert not fresh.path.exists()


@pytest.mark.parametrize("value", [True, False], ids=["on", "off"])
def test_setting_the_menu_entry_first_means_no_notice(notices, fresh, value) -> None:
    fresh.app.settings.redraw_on_sync_var.set(value)  # Tools > Redraw Ladder on Sync

    _sync(fresh, "Pump")

    assert notices == []
    assert read_settings(fresh.path) == SavedSettings(redraw_on_sync=value)
    assert fresh.desktop.calls == ([(111, 222)] if value else [])


def test_turning_the_setting_off_lasts_across_starts(notices, tk_root, tmp_path) -> None:
    path = tmp_path / "settings.json"
    AppSettings(path).redraw_on_sync_var.set(False)

    again = AppSettings(path)

    assert not again.redraw_on_sync
    assert not again.redraw_notice_due


def test_the_menu_command_shows_no_notice(notices, fresh) -> None:
    fresh.desktop.results.append(RedrawResult(RedrawOutcome.REFRESHED))

    fresh.app._connection.redraw_nicknames(after_sync=False)
    fresh.app.root.run(100)

    assert fresh.desktop.calls == [(111, 222)]
    assert notices == []
    assert fresh.app.settings.redraw_notice_due


def test_a_saved_notice_is_not_shown_again(notices, tk_root, tmp_path, desktop) -> None:
    path = tmp_path / "settings.json"
    assert write_settings(SavedSettings(redraw_notice_shown=True), path)
    app = _app()
    app.settings = AppSettings(path)
    store = _store(DatabaseSource())
    app._open_data(store)

    _sync(SimpleNamespace(app=app, store=store, desktop=desktop), "Pump")

    assert desktop.calls == [(111, 222)]
    assert notices == []


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

    def redraw(_desktop, pid, main):
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
        '⚠ Synced the nicknames into CLICK\'s database, but CLICK was busy (CLICK shows "Out"). '
        "Use Tools > Redraw Nicknames in CLICK to show them"
    )


def test_a_failed_redraw_after_sync_says_so(desktop) -> None:
    app = _app()
    desktop.results.append(OSError("access denied"))

    app._connection.redraw_nicknames(after_sync=True)
    app.root.run(100)

    message, style = _status(app)
    assert style == "error"
    assert message.startswith(
        "⚠ Synced the nicknames into CLICK's database, but CLICK did not redraw them"
    )
    assert "(access denied)" in message


def test_the_menu_command_on_a_busy_click_says_to_close_its_dialog(desktop) -> None:
    app = _app()
    desktop.results.append(RedrawResult(RedrawOutcome.BUSY, "CLICK's window is disabled"))

    app._connection.redraw_nicknames(after_sync=False)
    app.root.run(100)

    assert _status(app) == (
        "⚠ CLICK is busy (CLICK's window is disabled). Close any open CLICK dialog or wait, then try again",
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
    assert message.startswith("⚠ Synced the nicknames into CLICK's database, but CLICK was busy")


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
    running.pop()()  # CLICK's window closed, and the redraw ends while another window is connected.
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
    assert shown[1][0].startswith(
        "⚠ Synced the nicknames into CLICK's database, but CLICK was busy"
    )
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
