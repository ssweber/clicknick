"""Main-window information architecture and status wiring."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.services.workspace_mirror import (
    MirrorState,
    MirrorStatus,
    WorkspaceDirectoryInfo,
)
from clicknick.services.workspace_service import WorkspaceState, WorkspaceStatus


@pytest.mark.parametrize(
    ("label", "mode"),
    [
        ("None", "none"),
        ("Prefix", "prefix"),
        ("Contains", "contains"),
        ("Fuzzy", "containsplus"),
    ],
)
def test_match_breadth_selector_preserves_filter_modes(label: str, mode: str) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.match_breadth_var = MagicMock(get=MagicMock(return_value=label))
    app.settings = SimpleNamespace(search_var=MagicMock())

    app._on_match_breadth_selected()

    app.settings.search_var.set.assert_called_once_with(mode)


def test_workspace_details_refresh_from_shared_status_models(tmp_path: Path) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    variable_names = (
        "workspace_status_var",
        "mirror_status_var",
        "mirror_detail_var",
        "mirror_path_var",
        "plc_name_var",
        "generated_dir_var",
        "source_project_var",
        "last_regenerated_var",
        "last_backup_var",
    )
    for name in variable_names:
        setattr(app, name, MagicMock())
    app.workspace_status_label = MagicMock()
    app._workspace_refresh_after_id = None
    app._get_workspace_status = MagicMock(
        return_value=WorkspaceStatus(WorkspaceState.CLEAN, "Clean")
    )
    mirror = tmp_path / "IMHERE Workspace"
    project = tmp_path / "Example.ckp"
    app._get_workspace_mirror_status = MagicMock(
        return_value=MirrorStatus(MirrorState.PAIRED, "Paired", path=mirror)
    )
    app._get_workspace_directory_info = MagicMock(
        return_value=WorkspaceDirectoryInfo(
            generated_dir=tmp_path / "pyrung_project",
            source_project=project,
            mirror_dir=mirror,
            last_regenerated_at=None,
            last_backup_at=None,
        )
    )
    app._current_plc_name = MagicMock(return_value="IMHERE")

    app._refresh_workspace_ui()

    app.workspace_status_var.set.assert_called_once_with("Clean")
    app.workspace_status_label.configure.assert_called_once_with(style="Connected.TLabel")
    app.mirror_status_var.set.assert_called_once_with("Paired")
    app.mirror_path_var.set.assert_called_once_with(str(mirror))
    app.plc_name_var.set.assert_called_once_with("IMHERE")
    app.source_project_var.set.assert_called_once_with(str(project))
