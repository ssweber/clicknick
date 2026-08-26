"""Capability status reported by the ClickNick live CLI."""

from __future__ import annotations

from enum import Enum

from clicknick.live.dispatch import DispatchContext, dispatch


class _Status(Enum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class _Analysis:
    def __init__(self, status: _Status, *, available: bool = False) -> None:
        self.status = status
        self.is_available = available
        self.project_dir = None


class _Store:
    loaded_row_count = 2
    user_overrides: dict[int, object] = {}


def test_ping_reports_loaded_source_rows() -> None:
    result = dispatch(DispatchContext(store=_Store()), "ping")

    assert "store: 2 rows" in result


def test_ping_reports_unsaved_project_capability() -> None:
    ctx = DispatchContext(project_saved=False)

    assert dispatch(ctx, "ping").endswith("status: project unsaved | only tag commands available")


def test_ping_reports_pyrung_live_when_project_is_ready() -> None:
    ctx = DispatchContext(
        analysis=_Analysis(_Status.READY, available=True),
        project_saved=True,
        pyrung_live_available=True,
    )

    assert dispatch(ctx, "ping").endswith("status: pyrung live available")


def test_ping_prompts_for_console_when_project_is_ready_but_dap_is_closed() -> None:
    ctx = DispatchContext(
        analysis=_Analysis(_Status.READY, available=True),
        project_saved=True,
    )

    assert dispatch(ctx, "ping").endswith("status: project ready | open Console for pyrung live")


def test_ping_reports_project_preparing_during_analysis() -> None:
    ctx = DispatchContext(
        analysis=_Analysis(_Status.BUILDING),
        project_saved=True,
    )

    assert dispatch(ctx, "ping").endswith("status: pyrung project preparing")


def test_ping_reports_project_unavailable_after_analysis_failure() -> None:
    ctx = DispatchContext(
        analysis=_Analysis(_Status.FAILED),
        project_saved=True,
    )

    assert dispatch(ctx, "ping").endswith("status: pyrung project unavailable")
