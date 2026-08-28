"""Main-window information architecture and status wiring."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from clicknick.app import ClickNickApp
from clicknick.services.workspace_mirror import (
    MirrorState,
    MirrorStatus,
    WorkspaceDirectoryInfo,
)
from clicknick.services.workspace_service import WorkspaceState, WorkspaceStatus


@pytest.mark.parametrize(
    ("index", "mode"),
    [
        (0, "none"),
        (1, "prefix"),
        (2, "contains"),
        (3, "containsplus"),
    ],
)
def test_match_mode_slider_preserves_filter_modes(index: int, mode: str) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.match_mode_index_var = MagicMock()
    app.settings = SimpleNamespace(search_var=MagicMock())

    app._on_match_mode_changed(str(index))

    app.match_mode_index_var.set.assert_called_once_with(float(index))
    app.settings.search_var.set.assert_called_once_with(mode)


def test_autocomplete_options_menu_uses_existing_setting_variables() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.settings = SimpleNamespace(
        sort_by_nickname_var=object(),
        show_info_tooltip_var=object(),
        exclude_sc_sd_var=object(),
    )
    app._on_sort_option_changed = MagicMock()
    menu = MagicMock()

    app._populate_autocomplete_options_menu(menu)

    assert menu.add_checkbutton.call_args_list == [
        call(
            label="Sort A→Z",
            variable=app.settings.sort_by_nickname_var,
            command=app._on_sort_option_changed,
        ),
        call(
            label="Show Tooltips",
            variable=app.settings.show_info_tooltip_var,
        ),
        call(
            label="Exclude SC/SD Addresses",
            variable=app.settings.exclude_sc_sd_var,
        ),
    ]


def test_workspace_options_menu_exposes_mirror_and_folder_actions() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._sync_workspace_mirror = MagicMock()
    app._open_generated_workspace = MagicMock()
    app._open_mirror_folder = MagicMock()
    app._open_mirror_setup_window = MagicMock()
    menu = MagicMock()

    app._populate_workspace_options_menu(menu)

    assert menu.mock_calls == [
        call.add_command(label="Sync Now", command=app._sync_workspace_mirror),
        call.add_command(
            label="Open Generated Workspace",
            command=app._open_generated_workspace,
        ),
        call.add_command(label="Open Mirror Folder", command=app._open_mirror_folder),
        call.add_separator(),
        call.add_command(
            label="View/Setup Mirror...",
            command=app._open_mirror_setup_window,
        ),
    ]


def test_workspace_details_refresh_from_shared_status_models(tmp_path: Path) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    variable_names = (
        "workspace_status_var",
        "workspace_group_title_var",
        "project_name_var",
        "mirror_status_var",
        "mirror_detail_var",
        "mirror_path_var",
        "mirror_setup_action_var",
        "plc_name_var",
        "generated_dir_var",
        "source_project_var",
        "last_regenerated_var",
        "last_backup_var",
    )
    for name in variable_names:
        setattr(app, name, MagicMock())
    app._workspace_refresh_after_id = None
    app._workspace_config = object()
    app.connected_click_filename = "Example.ckp"
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
    app.workspace_group_title_var.set.assert_called_once_with("Workspace - Clean")
    app.project_name_var.set.assert_called_once_with("Example.ckp")
    app.mirror_status_var.set.assert_called_once_with("Paired")
    app.mirror_path_var.set.assert_called_once_with(str(mirror))
    app.mirror_setup_action_var.set.assert_called_once_with("Change...")
    app.plc_name_var.set.assert_called_once_with("IMHERE")
    app.source_project_var.set.assert_called_once_with(str(project))
