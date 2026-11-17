"""User-facing status for the generated CLICK workspace."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .analysis_service import AnalysisStatus
from .project_workspace import plc_source_is_modified

if TYPE_CHECKING:
    from .analysis_service import AnalysisService


class WorkspaceState(enum.Enum):
    """The states that a workspace status can be in."""

    UNAVAILABLE = "unavailable"
    PREPARING = "preparing"
    CLEAN = "clean"
    MODIFIED = "modified"
    FAILED = "failed"


@dataclass(frozen=True)
class WorkspaceStatus:
    """The status of the generated workspace, as plain data that any view can show."""

    state: WorkspaceState
    label: str
    detail: str | None = None
    changed_rungs: int = 0


def get_workspace_status(
    analysis: AnalysisService | None, *, staged_rungs: int = 0
) -> WorkspaceStatus:
    """Describe the current generated workspace without touching Tkinter."""
    if analysis is None or analysis.status is AnalysisStatus.IDLE:
        return WorkspaceStatus(WorkspaceState.UNAVAILABLE, "Unavailable")
    if analysis.status is AnalysisStatus.BUILDING:
        return WorkspaceStatus(WorkspaceState.PREPARING, "Preparing")
    if analysis.status is AnalysisStatus.FAILED:
        if getattr(analysis, "system_nickname_repairs", ()):
            label = "Run Tools > Repairs > System Nicknames"
        elif getattr(analysis, "needs_comment_upgrade", False):
            label = "Run Tools > Repairs > Upgrade Project"
        else:
            # analysis.error holds the reason that the failed step reported. A workspace
            # folder from an earlier build may still exist.
            label = "Could not build the workspace"
        return WorkspaceStatus(WorkspaceState.FAILED, label, detail=analysis.error)

    project_dir = analysis.project_dir
    if project_dir is None:
        return WorkspaceStatus(WorkspaceState.UNAVAILABLE, "Unavailable")

    try:
        modified = plc_source_is_modified(project_dir)
    except OSError as exc:
        return WorkspaceStatus(WorkspaceState.FAILED, "Status error", detail=str(exc))

    if staged_rungs > 0:
        noun = "rung" if staged_rungs == 1 else "rungs"
        return WorkspaceStatus(
            WorkspaceState.MODIFIED,
            f"{staged_rungs} changed {noun}",
            changed_rungs=staged_rungs,
        )
    if modified:
        return WorkspaceStatus(WorkspaceState.MODIFIED, "Modified")
    return WorkspaceStatus(WorkspaceState.CLEAN, "Clean")
