"""DAP simulation lifecycle commands for live editing.

Manages the pyrung DAP subprocess via DapService. The agent interacts with
the running simulation through pyrung-live; these commands only handle
start/stop/status from the ClickNick side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dispatch import DispatchContext


def _cmd_start(ctx: DispatchContext, _parts: list[str]) -> str:
    from ..services.dap_service import DapService, SimState

    analysis = ctx.analysis
    if analysis is None or not analysis.is_available:
        raise ValueError("analysis not available (no Click project connected)")
    project_dir = analysis.project_dir
    if project_dir is None or not project_dir.is_dir():
        raise ValueError("pyrung project not persisted to disk yet")

    dap = ctx.dap
    if dap is not None and dap.state not in (SimState.IDLE, SimState.STOPPED, SimState.ERROR):
        return f"DAP already running (state: {dap.state.value})"

    if dap is None:
        dap = DapService()
        ctx.dap = dap

    dap.launch(project_dir)
    return f"OK: DAP launched from {project_dir} (state: {dap.state.value})"


def _cmd_stop(ctx: DispatchContext, _parts: list[str]) -> str:
    if ctx.dap is None:
        return "DAP not running"
    ctx.dap.terminate()
    return "OK: DAP stopped"


def _cmd_status(ctx: DispatchContext, _parts: list[str]) -> str:
    if ctx.dap is None:
        return "state: idle (not started)"
    return f"state: {ctx.dap.state.value}"


_SUBCOMMANDS = {
    "start": _cmd_start,
    "stop": _cmd_stop,
    "status": _cmd_status,
}


def dispatch_dap(ctx: DispatchContext, parts: list[str]) -> str:
    """Route ``dap <subcommand> ...`` to the right handler."""
    if not parts:
        raise ValueError(f"usage: dap <subcommand> ...  (subcommands: {', '.join(_SUBCOMMANDS)})")

    sub = parts[0].lower()
    handler = _SUBCOMMANDS.get(sub)
    if handler is None:
        raise ValueError(f"unknown dap subcommand {sub!r} (expected: {', '.join(_SUBCOMMANDS)})")
    return handler(ctx, parts[1:])
