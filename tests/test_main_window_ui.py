"""Main-window information architecture and status wiring."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from clicknick.app import ClickNickApp
from clicknick.services.workspace_mirror import WorkspaceDirectoryInfo
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


def test_workspace_options_menu_exposes_active_folder_and_setup() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._workspace_config = None
    app._open_workspace = MagicMock()
    app._open_mirror_setup_window = MagicMock()
    menu = MagicMock()

    app._populate_workspace_options_menu(menu)

    assert menu.mock_calls == [
        call.add_command(
            label="Open Workspace",
            command=app._open_workspace,
            state="disabled",
        ),
        call.add_separator(),
        call.add_command(
            label="View/Setup Workspace...",
            command=app._open_mirror_setup_window,
        ),
    ]


def test_open_workspace_menu_items_follow_durable_configuration() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.workspace_options_menu = MagicMock()
    app._workspace_options_open_index = 0
    app.workspace_menu = MagicMock()
    app._workspace_menu_open_index = 3
    app._workspace_config = None

    app._refresh_workspace_menu_states()

    app.workspace_options_menu.entryconfigure.assert_called_once_with(0, state="disabled")
    app.workspace_menu.entryconfigure.assert_called_once_with(3, state="disabled")

    app.workspace_options_menu.reset_mock()
    app.workspace_menu.reset_mock()
    app._workspace_config = object()

    app._refresh_workspace_menu_states()

    app.workspace_options_menu.entryconfigure.assert_called_once_with(0, state="normal")
    app.workspace_menu.entryconfigure.assert_called_once_with(3, state="normal")


def test_main_window_is_revealed_once_at_its_settled_requested_size() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app.root.winfo_reqwidth.return_value = 760
    app.root.winfo_reqheight.return_value = 450
    app._main_window_shown = False

    app._show_main_window()
    app._show_main_window()

    app.root.update_idletasks.assert_called_once_with()
    app.root.geometry.assert_called_once_with("760x450")
    app.root.deiconify.assert_called_once_with()
    assert app._main_window_shown is True


def test_run_finishes_initial_refresh_before_revealing_main_window() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app.refresh_click_instances = MagicMock()
    app._show_main_window = MagicMock()
    lifecycle = MagicMock()
    lifecycle.attach_mock(app.refresh_click_instances, "refresh")
    lifecycle.attach_mock(app._show_main_window, "show")
    lifecycle.attach_mock(app.root.mainloop, "mainloop")

    app.run()

    assert lifecycle.mock_calls == [call.refresh(), call.show(), call.mainloop()]


def test_workspace_details_refresh_from_shared_status_models(tmp_path: Path) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    variable_names = (
        "workspace_status_var",
        "workspace_group_title_var",
        "project_name_var",
        "mirror_status_var",
        "mirror_detail_var",
        "mirror_path_var",
        "mirror_setup_status_var",
        "plc_name_var",
        "generated_dir_var",
        "workspace_config_path_var",
        "last_regenerated_var",
        "last_backup_var",
    )
    for name in variable_names:
        setattr(app, name, MagicMock())
    app._workspace_refresh_after_id = None
    app._workspace_config = object()
    app._workspace_mirror_error = None
    app.connected_click_filename = "Example.ckp"
    app._get_workspace_status = MagicMock(
        return_value=WorkspaceStatus(WorkspaceState.CLEAN, "Clean")
    )
    mirror = tmp_path / "IMHERE Workspace"
    project = tmp_path / "Example.ckp"
    app._workspace_display_dir = MagicMock(return_value=mirror)
    app._get_workspace_directory_info = MagicMock(
        return_value=WorkspaceDirectoryInfo(
            generated_dir=tmp_path / "pyrung_project",
            config_path=project,
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
    app.mirror_status_var.set.assert_called_once_with("Durable")
    app.mirror_path_var.set.assert_called_once_with(str(mirror))
    app.mirror_setup_status_var.set.assert_called_once_with("✓ Configured")
    app.plc_name_var.set.assert_called_once_with("IMHERE")
    app.workspace_config_path_var.set.assert_called_once_with(str(project))
