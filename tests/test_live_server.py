"""LiveServer runs queued commands on the Tk thread without waiting on dialogs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.live.dispatch import dispatch
from clicknick.live.server import LiveServer, _Request


class MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def load_all_addresses(self):
        return {}

    def save_changes(self, rows):
        return len(rows)


class FakeRoot:
    """Collects ``after`` callbacks; ``run_idle`` runs the ones due now."""

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


def _edited_store() -> AddressStore:
    store = AddressStore(MockDataSource())
    store.load_initial_data()
    with store.edit_session("edit") as session:
        session.set_field(get_addr_key("DS", 1), "nickname", "Level")
    return store


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

    assert first.done.is_set() and first.result.startswith("prompted: 1 unsaved change")
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
    """A build that published the workspace with new names, then failed to analyse it."""
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
