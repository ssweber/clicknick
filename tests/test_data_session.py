"""Tests for DataSession: the loaded data and the windows bound to it."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from clicknick.data_session import DataSession


class FakeStore:
    def __init__(self, *, unsaved: bool = False, save_error: Exception | None = None) -> None:
        self._unsaved = unsaved
        self.stop_file_monitoring = MagicMock()
        self.save_all_changes = MagicMock(side_effect=save_error)

    def has_unsaved_changes(self) -> bool:
        return self._unsaved


class FakeWindow:
    def __init__(self, session: DataSession | None = None, *, unsaved: bool = False) -> None:
        self.session = session
        self.unsaved = unsaved
        self.closed = False
        self.saved = False

    def close_without_prompt(self) -> None:
        self.closed = True
        # Real windows unregister themselves while the session closes them.
        if self.session is not None:
            self.session.unregister_editor(self)
            self.session.unregister_dataview_window(self)

    def has_unsaved_changes(self) -> bool:
        return self.unsaved

    def save_all(self) -> None:
        self.saved = True


@pytest.fixture
def answers(monkeypatch):
    """Queue answers for askyesnocancel; record each prompt."""
    queue: list[bool | None] = []
    prompts: list[str] = []

    def ask(title, message, **kwargs):
        prompts.append(message)
        return queue.pop(0)

    monkeypatch.setattr("tkinter.messagebox.askyesnocancel", ask)
    monkeypatch.setattr("tkinter.messagebox.showerror", MagicMock())
    return queue, prompts


def test_force_close_closes_every_window_and_stops_monitoring() -> None:
    session = DataSession(FakeStore())
    editors = [FakeWindow(session), FakeWindow(session)]
    dataview = FakeWindow(session)
    for editor in editors:
        session.register_editor(editor)
    session.register_dataview_window(dataview)
    assert session.has_open_windows

    session.force_close()

    assert all(editor.closed for editor in editors)
    assert dataview.closed
    assert not session.has_open_windows
    session.store.stop_file_monitoring.assert_called_once()


def test_close_without_unsaved_changes_does_not_prompt(answers) -> None:
    _queue, prompts = answers
    session = DataSession(FakeStore())
    editor = FakeWindow(session)
    session.register_editor(editor)

    assert session.close(prompt_save=True)

    assert prompts == []
    assert editor.closed


def test_cancel_at_address_prompt_closes_nothing(answers) -> None:
    queue, _prompts = answers
    queue.append(None)
    session = DataSession(FakeStore(unsaved=True))
    editor = FakeWindow(session)
    session.register_editor(editor)

    assert not session.close(prompt_save=True)

    assert not editor.closed
    session.store.save_all_changes.assert_not_called()
    session.store.stop_file_monitoring.assert_not_called()


def test_dataview_prompt_comes_first_and_cancel_stops_there(answers) -> None:
    queue, prompts = answers
    queue.append(None)
    session = DataSession(FakeStore(unsaved=True))
    dataview = FakeWindow(session, unsaved=True)
    session.register_dataview_window(dataview)

    assert not session.close(prompt_save=True)

    assert len(prompts) == 1 and "Dataview" in prompts[0]
    assert not dataview.closed


def test_yes_saves_both_then_closes(answers) -> None:
    queue, prompts = answers
    queue.extend([True, True])
    session = DataSession(FakeStore(unsaved=True))
    dataview = FakeWindow(session, unsaved=True)
    session.register_dataview_window(dataview)

    assert session.close(prompt_save=True)

    assert len(prompts) == 2
    assert dataview.saved and dataview.closed
    session.store.save_all_changes.assert_called_once()


def test_failed_save_keeps_everything_open(answers) -> None:
    queue, _prompts = answers
    queue.append(True)
    session = DataSession(FakeStore(unsaved=True, save_error=RuntimeError("locked")))
    editor = FakeWindow(session)
    session.register_editor(editor)

    assert not session.close(prompt_save=True)

    assert not editor.closed
    session.store.stop_file_monitoring.assert_not_called()
