"""Main-window information architecture and status wiring."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from clicknick.app import ClickNickApp
from clicknick.connection_session import ClickConnection
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
    app._request_ui_refresh = MagicMock()
    app.match_mode_index_var = MagicMock()
    app.settings = SimpleNamespace(search_var=MagicMock())

    app._on_match_mode_changed(str(index))

    app.match_mode_index_var.set.assert_called_once_with(float(index))
    app.settings.search_var.set.assert_called_once_with(mode)


def test_autocomplete_options_menu_uses_existing_setting_variables() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
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
    app._request_ui_refresh = MagicMock()
    app._workspace_config = None
    app._workspace_display_dir = MagicMock(return_value=None)
    app._open_workspace = MagicMock()
    app._open_mirror_setup_window = MagicMock()
    menu = MagicMock()

    app._populate_workspace_options_menu(menu)

    assert menu.mock_calls == [
        call.add_command(
            label="Open Temporary Workspace",
            command=app._open_workspace,
            state="disabled",
        ),
        call.add_separator(),
        call.add_command(
            label="View/Setup Workspace...",
            command=app._open_mirror_setup_window,
        ),
    ]


def test_open_workspace_menu_items_follow_active_directory(tmp_path) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app.workspace_options_menu = MagicMock()
    app._workspace_options_open_index = 0
    app.workspace_menu = MagicMock()
    app._workspace_menu_open_index = 3
    app._workspace_config = None
    app._workspace_display_dir = MagicMock(return_value=None)

    app._refresh_workspace_menu_states()

    app.workspace_options_menu.entryconfigure.assert_called_once_with(
        0, label="Open Temporary Workspace", state="disabled"
    )
    app.workspace_menu.entryconfigure.assert_called_once_with(
        3, label="Open Temporary Workspace", state="disabled"
    )

    app.workspace_options_menu.reset_mock()
    app.workspace_menu.reset_mock()
    app._workspace_display_dir.return_value = tmp_path

    app._refresh_workspace_menu_states()

    app.workspace_options_menu.entryconfigure.assert_called_once_with(
        0, label="Open Temporary Workspace", state="normal"
    )
    app.workspace_menu.entryconfigure.assert_called_once_with(
        3, label="Open Temporary Workspace", state="normal"
    )

    app.workspace_options_menu.reset_mock()
    app.workspace_menu.reset_mock()
    app._workspace_config = object()

    app._refresh_workspace_menu_states()

    app.workspace_options_menu.entryconfigure.assert_called_once_with(
        0, label="Open Workspace", state="normal"
    )
    app.workspace_menu.entryconfigure.assert_called_once_with(
        3, label="Open Workspace", state="normal"
    )


def test_main_window_is_revealed_once_at_its_settled_requested_size() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
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
    app._request_ui_refresh = MagicMock()
    app.root = MagicMock()
    app.refresh_click_instances = MagicMock()
    app._show_main_window = MagicMock()
    lifecycle = MagicMock()
    lifecycle.attach_mock(app.refresh_click_instances, "refresh")
    lifecycle.attach_mock(app._show_main_window, "show")
    lifecycle.attach_mock(app.root.mainloop, "mainloop")

    app.run()

    assert lifecycle.mock_calls == [call.refresh(), call.show(), call.mainloop()]


def test_ui_refresh_sets_title_and_workspace_details(tmp_path: Path) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
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
        "test_group_title_var",
        "simulation_action_var",
    )
    for name in variable_names:
        setattr(app, name, MagicMock())
    app._workspace_refresh_after_id = None
    app._workspace_config = object()
    app._workspace_mirror_error = None
    app._click = ClickConnection("1", 2, "Example.ckp")
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
    app.repairs_menu = MagicMock()
    app._repairs_system_nicknames_index = 0
    app._session = SimpleNamespace(
        analysis=SimpleNamespace(system_nickname_repairs=(object(),)),
        synced_pending=2,
        simulation=None,
    )
    app._data = None
    app.root = MagicMock()

    app._refresh_ui()

    app.root.title.assert_called_once_with(
        "ClickNick - Example.ckp (2 tags synced - Save in CLICK)"
    )

    app.workspace_status_var.set.assert_called_once_with("Clean")
    app.workspace_group_title_var.set.assert_called_once_with("Workspace - Clean")
    app.project_name_var.set.assert_called_once_with("Example.ckp")
    app.mirror_status_var.set.assert_called_once_with("Durable")
    app.mirror_path_var.set.assert_called_once_with(str(mirror))
    app.mirror_setup_status_var.set.assert_called_once_with("✓ Configured")
    app.plc_name_var.set.assert_called_once_with("IMHERE")
    app.test_group_title_var.set.assert_called_once_with("Test - Sim off")
    app.workspace_config_path_var.set.assert_called_once_with(str(project))
    app.repairs_menu.entryconfigure.assert_called_once_with(0, state="normal")


def test_changing_shown_state_schedules_one_idle_refresh() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._ui_refresh_id = None
    app._refresh_ui = MagicMock()

    app._click = ClickConnection("1", 2, "Example.ckp")
    app._data = None
    app._session = None
    app._workspace_config = None
    app._workspace_matches = []
    app._workspace_mirror_error = "missing"

    app.root.after_idle.assert_called_once()
    app._refresh_ui.assert_not_called()
    app.root.after_idle.call_args.args[0]()
    app._refresh_ui.assert_called_once_with()
    assert app._ui_refresh_id is None
    assert app._click == ClickConnection("1", 2, "Example.ckp")
    assert app._workspace_mirror_error == "missing"

    app._session = None
    assert app.root.after_idle.call_count == 2


def test_simulation_toggle_reports_and_switches_state() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app._session = None
    assert app._simulation_summary() == ("Test - Sim off", "Start")

    simulation = SimpleNamespace(
        enabled=True, summary_text="on :502", turn_off=MagicMock(), turn_on=MagicMock()
    )
    app._session = SimpleNamespace(simulation=simulation)
    assert app._simulation_summary() == ("Test - Sim on :502", "Stop")

    app._toggle_simulation()
    simulation.turn_off.assert_called_once_with()

    simulation.enabled = False
    app._simulation_for_window = MagicMock(return_value=simulation)
    app._toggle_simulation()
    simulation.turn_on.assert_called_once_with()


@pytest.mark.parametrize("answer", [True, False])
def test_new_legacy_encodings_pop_up_and_offer_review_changes(monkeypatch, answer: bool) -> None:
    from clicknick.ladder.program import LegacyEncoding

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._ui_refresh_id = None
    app._refresh_ui = MagicMock()
    app._workspace_rung_apply = MagicMock()
    detail = "it is stored as 16-bit and CLICK runs it as 4464."
    found = (LegacyEncoding("main.csv", "Main Program", 12, "Math", "H70000", detail),)
    app._session = SimpleNamespace(legacy_encodings_to_report=MagicMock(return_value=found))
    ask = MagicMock(return_value=answer)
    monkeypatch.setattr("clicknick.app.messagebox.askyesno", ask)

    app._report_legacy_encodings()

    message = ask.call_args.args[1]
    assert f"Main Program rung 12, Math H70000: {detail}" in message
    assert "Open Review Changes now?" in message
    assert app._workspace_rung_apply.called is answer

    # The next build finds nothing new, so no popup shows
    ask.reset_mock()
    app._session.legacy_encodings_to_report.return_value = ()
    app._report_legacy_encodings()
    ask.assert_not_called()


def _popup_app(found):
    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._ui_refresh_id = None
    app._refresh_ui = MagicMock()
    app._workspace_rung_apply = MagicMock()
    app._session = SimpleNamespace(legacy_encodings_to_report=MagicMock(return_value=found))
    return app


def _unreadable(rung: int):
    from clicknick.ladder.program import LegacyEncoding

    detail = "ClickNick cannot read this Compare."
    return LegacyEncoding(
        "subroutines/Conf_Compare.csv", "Conf_Compare", rung, "Compare", "", detail, True
    )


def test_rungs_clicknick_cannot_read_pop_up_without_offering_the_workspace(monkeypatch) -> None:
    app = _popup_app((_unreadable(4),))
    warn, ask = MagicMock(), MagicMock()
    monkeypatch.setattr("clicknick.app.messagebox.showwarning", warn)
    monkeypatch.setattr("clicknick.app.messagebox.askyesno", ask)

    app._report_legacy_encodings()

    ask.assert_not_called()
    assert warn.call_args.args[0] == "Paste Again"
    message = warn.call_args.args[1]
    assert message.startswith("ClickNick cannot read these rungs in CLICK:\n")
    assert "  Conf_Compare rung 4, Compare: ClickNick cannot read this Compare." in message
    assert "empty rung" in message
    assert "old encoding" not in message
    app._workspace_rung_apply.assert_not_called()


def test_a_program_csv_laddercodec_cannot_read_pops_up_too(monkeypatch) -> None:
    from clicknick.ladder.program import LegacyEncoding

    copy = LegacyEncoding("main.csv", "Main Program", None, "", "", "Invalid marker 'X'", True)
    app = _popup_app((copy,))
    warn = MagicMock()
    monkeypatch.setattr("clicknick.app.messagebox.showwarning", warn)

    app._report_legacy_encodings()

    message = warn.call_args.args[1]
    assert message.startswith(
        "Paste these programs into CLICK again from your own copy, or fix them in CLICK:\n\n"
        "  Main Program: Invalid marker"
    )
    assert "empty rung" not in message


def test_both_kinds_pop_up_together_and_offer_review_changes(monkeypatch) -> None:
    from clicknick.ladder.program import LegacyEncoding

    legacy = LegacyEncoding("main.csv", "Main Program", 12, "Math", "H70000", "it is stored...")
    app = _popup_app((legacy, _unreadable(4)))
    ask = MagicMock(return_value=True)
    monkeypatch.setattr("clicknick.app.messagebox.askyesno", ask)

    app._report_legacy_encodings()

    message = ask.call_args.args[1]
    assert "Conf_Compare rung 4" in message
    assert "Main Program rung 12, Math H70000" in message
    assert message.endswith("Open Review Changes now?")
    app._workspace_rung_apply.assert_called_once_with()
