"""Tests for the rung preview window actions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from clicknick.views.rung_preview_window import RungPreviewWindow


def test_copy_all_remains_available_after_copy(monkeypatch, tmp_path) -> None:
    result = SimpleNamespace(payload=b"proposal", addresses_inserted=0, mdb_error=None)
    copy_to_clipboard = Mock()
    monkeypatch.setattr("clicknick.ladder.program.prepare_rungs_load", lambda *_args, **_kw: result)
    monkeypatch.setattr("clicknick.ladder.clipboard.copy_to_clipboard", copy_to_clipboard)

    window = SimpleNamespace(
        _pending_dir=tmp_path,
        _read_csv=lambda: [object()],
        _get_mdb_path=None,
        _get_click_hwnd=None,
        _groups=[[1]],
        _group_idx=0,
        _copied=False,
        _copy_all_btn=Mock(),
        _copy_btn=Mock(),
        _next_btn=Mock(),
        _status_var=Mock(),
        _csv_stem="main",
    )

    RungPreviewWindow._on_copy_all(window)

    copy_to_clipboard.assert_called_once_with(b"proposal", owner_hwnd=None)
    window._copy_all_btn.configure.assert_called_once_with(state="normal")
    assert window._copied is True
