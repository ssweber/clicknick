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
    """Small state vocabulary shared by workspace UI surfaces."""

    UNAVAILABLE = "unavailable"
    PREPARING = "preparing"
    CLEAN = "clean"
    MODIFIED = "modified"
    FAILED = "failed"


@dataclass(frozen=True)
class WorkspaceStatus:
    """Presentation-neutral workspace state."""

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
        repairs = getattr(analysis, "system_nickname_repairs", ())
        return WorkspaceStatus(
            WorkspaceState.FAILED,
            "System names need repair" if repairs else "Build failed",
            detail=analysis.error,
        )

    project_dir = analysis.project_dir
    if not analysis.is_available or project_dir is None:
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
