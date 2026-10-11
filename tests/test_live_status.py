"""Capability status reported by the ClickNick live CLI."""

from __future__ import annotations

from enum import Enum

from clicknick.live.dispatch import DispatchContext, _status_footer, dispatch


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


def test_workflow_footer_composes_outgoing_changes_before_capability() -> None:
    store = _Store()
    store.user_overrides = {1: object(), 2: object()}
    ctx = DispatchContext(
        store=store,
        analysis=_Analysis(_Status.READY, available=True),
        synced_pending=7,
        staged_rungs=31,
    )

    assert _status_footer(ctx) == (
        "\n[2 tags staged | 7 tags synced | 31 rungs staged | "
        "Next: Sync tags in ClickNick, paste rungs if needed, then Save in CLICK]"
        "\n[project ready | open Console for pyrung live]"
    )


def test_workflow_footer_uses_singular_nouns() -> None:
    store = _Store()
    store.user_overrides = {1: object()}

    assert _status_footer(DispatchContext(store=store)) == (
        "\n[1 tag staged | Next: Sync in ClickNick]"
    )
    assert _status_footer(DispatchContext(store=_Store(), synced_pending=1)) == (
        "\n[1 tag synced | Next: Save in CLICK]"
    )
    assert _status_footer(DispatchContext(store=_Store(), staged_rungs=1)) == (
        "\n[1 rung staged | Next: Paste if needed, then Save in CLICK]"
    )


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


def test_failed_analysis_exposes_workspace_and_source_listing(tmp_path) -> None:
    source = tmp_path / "src" / "plc"
    source.mkdir(parents=True)
    (source / "main.py").write_text("with rung():\n    time_drum(...).reset()\n", encoding="utf-8")
    analysis = _Analysis(_Status.FAILED)
    analysis.project_dir = tmp_path
    ctx = DispatchContext(store=_Store(), analysis=analysis, project_saved=True)

    result = dispatch(ctx, "ping")
    assert f"project: {tmp_path}" in result
    assert "workspace available | analysis failed" in result
    assert "main" in dispatch(ctx, "rung list")
