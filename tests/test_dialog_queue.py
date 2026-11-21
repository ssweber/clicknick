"""ClickNick shows the message boxes that open after a build one at a time.

On Windows, Tk keeps running ``after`` callbacks while a message box is open. The end of a
workspace build schedules several reports with ``after``. If each report opened its box at
once, the boxes would open on top of each other. In these tests, a stand-in for the Tk root
runs the waiting callbacks while a box is open. Tk does the same on Windows.
"""

from __future__ import annotations

import tkinter
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.connection_controller import REDRAW_NOTICE, REDRAW_ON_SYNC, ConnectionController
from clicknick.connection_session import ClickConnection, ConnectionSession
from clicknick.ladder.program import LegacyEncoding
from clicknick.utils.dialog_queue import DialogQueue
from clicknick.workspace_controller import WorkspaceController

LEGACY = LegacyEncoding("main.csv", "Main Program", 12, "Math", "H70000", "it is stored...")
WARNING = "ClickNick could not read the hardware configuration."
DROPPED = "Check Program no longer runs the rule old_rule."


class _ModalRoot:
    """A Tk root whose message boxes run the after() callbacks while they are open."""

    def __init__(self) -> None:
        self.waiting: list = []
        self.open = 0
        self.most_open = 0
        self.shown: list[tuple[str, str]] = []

    def after(self, _ms, callback):
        self.waiting.append(callback)
        return "after"

    def after_idle(self, callback):
        self.waiting.append(callback)
        return "after"

    def run(self) -> None:
        while self.waiting:
            self.waiting.pop(0)()

    def box(self, answer=None):
        """Return a stand-in for a messagebox function that answers *answer*."""

        def show(title, message, **kwargs):
            parent = kwargs.get("parent")
            if parent is not None and parent is not self and not parent.winfo_exists():
                raise tkinter.TclError("bad window path name")
            self.shown.append((title, message))
            self.open += 1
            self.most_open = max(self.most_open, self.open)
            try:
                self.run()  # The box's own message loop runs Tk's timers.
            finally:
                self.open -= 1
            return answer

        return show


@pytest.fixture
def root(monkeypatch) -> _ModalRoot:
    root = _ModalRoot()
    for name in ("showwarning", "showerror", "showinfo"):
        monkeypatch.setattr(f"tkinter.messagebox.{name}", root.box())
    for name in ("askyesno", "askokcancel"):
        monkeypatch.setattr(f"tkinter.messagebox.{name}", root.box(answer=False))
    return root


def _session(*, legacy=(), dropped=(), warning=None) -> SimpleNamespace:
    return SimpleNamespace(
        legacy_encodings_to_report=MagicMock(side_effect=[legacy, ()]),
        dropped_checks_to_report=MagicMock(
            side_effect=[tuple(SimpleNamespace(describe=lambda d=d: d) for d in dropped), ()]
        ),
        build_warning_to_report=MagicMock(side_effect=[warning, None]),
        record_rung_stage=MagicMock(),
    )


def _app(root: _ModalRoot, session: SimpleNamespace) -> ClickNickApp:
    app = ClickNickApp.__new__(ClickNickApp)
    app.__dict__["_ui_refresh_id"] = None
    app.__dict__["_session"] = session
    app.root = root
    app._dialogs = DialogQueue()
    app._request_ui_refresh = MagicMock()
    app._update_status = MagicMock()
    app._review_changes_windows = {}
    app.settings = SimpleNamespace(redraw_notice_due=True, mark_redraw_notice_shown=MagicMock())
    app._workspace = WorkspaceController(app)
    app._connection = ConnectionController(app)
    return app


def test_a_build_shows_its_reports_one_at_a_time(root) -> None:
    app = _app(root, _session(legacy=(LEGACY,), dropped=(DROPPED,), warning=WARNING))

    app._on_build_finished()
    root.run()

    assert root.most_open == 1
    assert [title for title, _ in root.shown] == ["Paste Again", "Check Program", "Workspace"]
    assert "Main Program rung 12, Math H70000" in root.shown[0][1]
    assert root.shown[1][1] == DROPPED
    assert root.shown[2][1] == WARNING


def test_a_build_that_ends_while_a_box_is_open_waits_for_it(root, monkeypatch) -> None:
    session = _session(legacy=(LEGACY,))
    # The first build has no warning. The second one has.
    session.build_warning_to_report = MagicMock(side_effect=[None, WARNING])
    app = _app(root, session)
    ended = False

    def paste_again(title, message, **kwargs):
        # A second build ends while the user reads the first build's box.
        nonlocal ended
        if not ended:
            ended = True
            app._on_build_finished()
        return root.box(answer=False)(title, message, **kwargs)

    monkeypatch.setattr("tkinter.messagebox.askyesno", paste_again)
    app._on_build_finished()
    root.run()

    assert root.most_open == 1
    assert [title for title, _ in root.shown] == ["Paste Again", "Workspace"]


def test_the_redraw_notice_after_a_sync_waits_for_a_build_report(root) -> None:
    app = _app(root, _session(warning=WARNING))

    app._on_build_finished()
    root.after(0, app._connection._show_redraw_notice)
    root.run()

    assert root.most_open == 1
    assert root.shown == [("Workspace", WARNING), (REDRAW_ON_SYNC, REDRAW_NOTICE)]
    app.settings.mark_redraw_notice_shown.assert_called_once_with()


def test_a_failed_reload_and_the_build_reports_open_one_at_a_time(root) -> None:
    app = _app(root, _session(legacy=(LEGACY,), dropped=(DROPPED,)))

    # The build worker schedules the reload's callback first, then the build's reports.
    root.after(0, lambda: app._workspace._reload_finished(False, "Could not read SC_.mdb"))
    app._on_build_finished()
    root.run()

    assert root.most_open == 1
    assert [title for title, _ in root.shown] == [
        "Reload from CLICK",
        "Paste Again",
        "Check Program",
    ]
    assert root.shown[0][1] == "Could not read SC_.mdb"
    assert root.shown[2][1] == DROPPED


def test_yes_to_paste_again_opens_review_changes_after_the_other_boxes(root, monkeypatch) -> None:
    app = _app(root, _session(legacy=(LEGACY,), dropped=(DROPPED,), warning=WARNING))
    monkeypatch.setattr("tkinter.messagebox.askyesno", root.box(answer=True))
    opened: list[tuple[int, list[str]]] = []

    def review_changes() -> None:
        # Review Changes shows its window and its first-time tips from after_idle.
        root.after_idle(lambda: opened.append((root.open, [title for title, _ in root.shown])))

    app._workspace.review_changes = review_changes

    app._on_build_finished()
    root.run()

    assert opened == [(0, ["Paste Again", "Check Program", "Workspace"])]


def test_a_check_program_box_shows_after_its_window_closed(root) -> None:
    app = _app(root, _session(warning=WARNING, dropped=(DROPPED,)))
    report_window = SimpleNamespace(winfo_exists=lambda: True)

    def check_program_while_the_warning_shows() -> None:
        # Choose Checks reports from its window. The user closes the window before the
        # Workspace box closes.
        app._report_dropped_checks(report_window)
        report_window.winfo_exists = lambda: False

    root.after(0, check_program_while_the_warning_shows)
    app._report_build_warning()

    assert [title for title, _ in root.shown] == ["Workspace", "Check Program"]


class _Builds:
    """The warning of the latest build, read the way ConnectionSession reads it."""

    def __init__(self, warning: str | None) -> None:
        self.warning = warning
        self.told: str | None = None

    def build_warning_to_report(self) -> str | None:
        if self.warning == self.told:
            return None
        self.told = self.warning
        return self.warning


@pytest.mark.parametrize("newer", [None, "The second build's warning."], ids=["none", "another"])
def test_a_box_that_waits_shows_the_newest_build(root, monkeypatch, newer) -> None:
    builds = _Builds(WARNING)
    session = _session(legacy=(LEGACY,))
    session.legacy_encodings_to_report = MagicMock(side_effect=[(LEGACY,), (), ()])
    session.dropped_checks_to_report = MagicMock(return_value=())
    session.build_warning_to_report = builds.build_warning_to_report
    app = _app(root, session)
    ended = False

    def paste_again(title, message, **kwargs):
        # While the user reads the first build's Paste Again box, the first build's other
        # reports run, and two more builds end. Both have the warning *newer*.
        nonlocal ended
        if not ended:
            ended = True
            root.run()
            builds.warning = newer
            app._on_build_finished()
            app._on_build_finished()
        return root.box(answer=False)(title, message, **kwargs)

    monkeypatch.setattr("tkinter.messagebox.askyesno", paste_again)
    app._on_build_finished()
    root.run()

    assert root.most_open == 1
    expected = [("Workspace", newer)] if newer else []
    assert root.shown[1:] == expected


class _InlineThread:
    """A thread that runs its target when it starts, on the caller's thread."""

    def __init__(self, target, **_kwargs) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


def test_the_csv_fallback_waits_for_the_database_connection_box(root, monkeypatch) -> None:
    def locked(**_kwargs):
        raise OSError("the database is locked")

    monkeypatch.setattr("clicknick.data.data_source.MdbDataSource", locked)
    monkeypatch.setattr("threading.Thread", _InlineThread)
    app = _app(root, _session(warning=WARNING))
    app._show_main_window = MagicMock()
    fallbacks: list[tuple[int, list[str]]] = []
    app._connection._connect_csv_fallback = lambda *_args: fallbacks.append(
        (root.open, [title for title, _ in root.shown])
    )
    session = ConnectionSession(ClickConnection("1", 2, "Main.ckp"))

    # The database load fails while the build's Workspace box is open.
    root.after(0, lambda: app._connection._load_instance_database(session))
    app._report_build_warning()

    assert [title for title, _ in root.shown] == ["Workspace", "Database Connection"]
    assert fallbacks == [(0, ["Workspace", "Database Connection"])]


# -- DialogQueue ---------------------------------------------------------------------------


def test_a_dialog_asked_for_while_another_shows_runs_after_it_closes() -> None:
    dialogs = DialogQueue()
    events: list[str] = []

    def first() -> None:
        events.append("first opens")
        dialogs.show(lambda: events.append("second"))
        events.append("first closes")

    dialogs.show(first)
    dialogs.show(lambda: events.append("third"))

    assert events == ["first opens", "first closes", "second", "third"]


def test_a_dialog_that_raises_does_not_lose_the_ones_after_it(caplog) -> None:
    dialogs = DialogQueue()
    events: list[str] = []

    def broken() -> None:
        dialogs.show(lambda: events.append("after"))
        raise RuntimeError("the window closed")

    dialogs.show(broken)
    dialogs.show(lambda: events.append("later"))

    assert events == ["after", "later"]
    assert "the window closed" in caplog.text
