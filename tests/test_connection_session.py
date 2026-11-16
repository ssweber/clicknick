"""ConnectionSession lifetime: made on connect, before CLICK's database loads."""

from __future__ import annotations

from unittest.mock import MagicMock

from clicknick.connection_session import (
    NO_DATABASE,
    ClickConnection,
    ConnectionSession,
    SavedProgram,
)


class _Root:
    def after(self, _delay, callback):
        callback()


def _saved_project(tmp_path, monkeypatch) -> None:
    """CLICK's folder holds a database and a saved program."""
    db_path = tmp_path / "SC_.mdb"
    db_path.write_text("db", encoding="utf-8")
    (tmp_path / "Scr1.tmp").write_text("ladder", encoding="utf-8")
    monkeypatch.setattr(
        "clicknick.utils.mdb_shared.find_click_database", lambda **_kwargs: str(db_path)
    )


def test_a_session_without_its_database_builds_nothing(tmp_path, monkeypatch) -> None:
    """Before the database loads, or with no database backend, nothing is built or watched."""
    _saved_project(tmp_path, monkeypatch)
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    session._start_analysis_thread = MagicMock()
    callback = MagicMock()

    session.start_analysis(_Root())
    assert session.reload_workspace_from_click(_Root(), callback) is False

    session._start_analysis_thread.assert_not_called()
    assert session.analysis is None
    assert session.scr_watcher is None
    callback.assert_called_once_with(False, NO_DATABASE)
    # Review Changes has nothing to compare with, as with nothing connected
    assert session.saved_program() == SavedProgram()


def test_a_session_builds_once_its_database_is_read(tmp_path, monkeypatch) -> None:
    _saved_project(tmp_path, monkeypatch)
    monkeypatch.setattr("clicknick.services.scr_watcher.ScrWatcher.start", MagicMock())
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    session._start_analysis_thread = MagicMock()

    session.has_database = True
    session.start_analysis(_Root())

    session._start_analysis_thread.assert_called_once_with(tmp_path, tmp_path / "SC_.mdb")
    assert session.scr_watcher is not None
    assert session.saved_program().session is session


def test_a_cancelled_or_closed_load_no_longer_counts() -> None:
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))

    first = session.begin_load()
    assert session.loads(first)
    session.cancel_load()
    assert not session.loads(first)

    second = session.begin_load()
    assert session.loads(second) and not session.loads(first)
    session.close()
    assert not session.loads(second)
