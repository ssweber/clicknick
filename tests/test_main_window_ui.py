"""Main-window information architecture and status wiring."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from clicknick.app import ClickNickApp
from clicknick.connection_session import ClickConnection, ConnectionSession
from clicknick.services.workspace_mirror import WorkspaceDirectoryInfo, WorkspacePairing
from clicknick.services.workspace_service import WorkspaceState, WorkspaceStatus
from clicknick.utils.dialog_queue import DialogQueue
from clicknick.workspace_controller import WorkspaceController


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
    workspace = WorkspaceController(SimpleNamespace(_session=None))
    workspace.display_dir = MagicMock(return_value=None)
    workspace.open_workspace = MagicMock()
    workspace.open_setup_window = MagicMock()
    menu = MagicMock()
    menu.index.return_value = 0

    workspace.populate_options_menu(menu)

    assert menu.mock_calls == [
        call.add_command(
            label="Open Temporary Workspace",
            command=workspace.open_workspace,
            state="disabled",
        ),
        call.index("end"),
        call.add_separator(),
        call.add_command(
            label="View/Setup Workspace...",
            command=workspace.open_setup_window,
        ),
    ]


def test_open_workspace_menu_items_follow_active_directory(tmp_path) -> None:
    app = SimpleNamespace(_session=None)
    workspace = WorkspaceController(app)
    workspace.display_dir = MagicMock(return_value=None)
    options_menu, workspace_menu = MagicMock(), MagicMock()
    options_menu.index.return_value = 0
    workspace_menu.index.return_value = 3
    workspace.add_open_entry(options_menu)
    workspace.add_open_entry(workspace_menu)
    options_menu.reset_mock()
    workspace_menu.reset_mock()

    workspace.refresh_menu_states()

    options_menu.entryconfigure.assert_called_once_with(
        0, label="Open Temporary Workspace", state="disabled"
    )
    workspace_menu.entryconfigure.assert_called_once_with(
        3, label="Open Temporary Workspace", state="disabled"
    )

    options_menu.reset_mock()
    workspace_menu.reset_mock()
    workspace.display_dir.return_value = tmp_path

    workspace.refresh_menu_states()

    options_menu.entryconfigure.assert_called_once_with(
        0, label="Open Temporary Workspace", state="normal"
    )
    workspace_menu.entryconfigure.assert_called_once_with(
        3, label="Open Temporary Workspace", state="normal"
    )

    options_menu.reset_mock()
    workspace_menu.reset_mock()
    app._session = SimpleNamespace(pairing=WorkspacePairing(object()))

    workspace.refresh_menu_states()

    options_menu.entryconfigure.assert_called_once_with(0, label="Open Workspace", state="normal")
    workspace_menu.entryconfigure.assert_called_once_with(3, label="Open Workspace", state="normal")


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
    app._connection = MagicMock()
    app._show_main_window = MagicMock()
    lifecycle = MagicMock()
    lifecycle.attach_mock(app._connection.refresh_click_instances, "refresh")
    lifecycle.attach_mock(app._show_main_window, "show")
    lifecycle.attach_mock(app.root.mainloop, "mainloop")

    app.run()

    assert lifecycle.mock_calls == [call.refresh(), call.show(), call.mainloop()]


def test_ui_refresh_sets_title_and_workspace_details(tmp_path: Path) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    variable_names = (
        "workspace_status_var",
        "workspace_detail_var",
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
    workspace = app._workspace = WorkspaceController(app)
    workspace.status = MagicMock(return_value=WorkspaceStatus(WorkspaceState.CLEAN, "Clean"))
    mirror = tmp_path / "IMHERE Workspace"
    project = tmp_path / "Example.ckp"
    workspace.display_dir = MagicMock(return_value=mirror)
    workspace.directory_info = MagicMock(
        return_value=WorkspaceDirectoryInfo(
            generated_dir=tmp_path / "pyrung_project",
            config_path=project,
            mirror_dir=mirror,
            last_regenerated_at=None,
            last_backup_at=None,
        )
    )
    workspace.plc_name = MagicMock(return_value="IMHERE")
    app.repairs_menu = MagicMock()
    app._repairs_system_nicknames_index = 0
    app._session = SimpleNamespace(
        click=ClickConnection("1", 2, "Example.ckp"),
        pairing=WorkspacePairing(object()),
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
    app.workspace_detail_var.set.assert_called_once_with("")

    # A failed build shows its reason under the workspace status
    workspace.status.return_value = WorkspaceStatus(
        WorkspaceState.FAILED, "Could not build the workspace", detail="TypeError: bad rung"
    )
    app._refresh_ui()

    app.workspace_detail_var.set.assert_called_with("TypeError: bad rung")
    app.workspace_group_title_var.set.assert_called_with(
        "Workspace - Could not build the workspace"
    )


def test_changing_shown_state_schedules_one_idle_refresh() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._ui_refresh_id = None
    app._refresh_ui = MagicMock()

    app._session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    app._data = None

    app.root.after_idle.assert_called_once()
    app._refresh_ui.assert_not_called()
    app.root.after_idle.call_args.args[0]()
    app._refresh_ui.assert_called_once_with()
    assert app._ui_refresh_id is None
    assert app._click == ClickConnection("1", 2, "Example.ckp")

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
    app._workspace = MagicMock()
    detail = "it is stored as 16-bit and CLICK runs it as 4464."
    found = (LegacyEncoding("main.csv", "Main Program", 12, "Math", "H70000", detail),)
    app._session = SimpleNamespace(legacy_encodings_to_report=MagicMock(return_value=found))
    app._dialogs = DialogQueue()
    ask = MagicMock(return_value=answer)
    monkeypatch.setattr("clicknick.app.messagebox.askyesno", ask)

    app._report_legacy_encodings()

    message = ask.call_args.args[1]
    assert f"Main Program rung 12, Math H70000: {detail}" in message
    assert "Open Review Changes now?" in message
    assert app._workspace.review_changes.called is answer

    # The next build finds nothing new, so it shows no popup.
    ask.reset_mock()
    app._session.legacy_encodings_to_report.return_value = ()
    app._report_legacy_encodings()
    ask.assert_not_called()


def _popup_app(found):
    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._ui_refresh_id = None
    app._refresh_ui = MagicMock()
    app._workspace = MagicMock()
    app._session = SimpleNamespace(legacy_encodings_to_report=MagicMock(return_value=found))
    app._dialogs = DialogQueue()
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
    assert message.startswith("ClickNick cannot copy these rungs from CLICK as they are:\n")
    assert "  Conf_Compare rung 4, Compare: ClickNick cannot read this Compare." in message
    assert "empty rung" in message
    assert "Paste it again from your own copy of the program" in message
    assert "old encoding" not in message
    app._workspace.review_changes.assert_not_called()


def test_a_rung_that_syntax_check_splits_is_not_told_to_be_pasted_again(monkeypatch) -> None:
    from clicknick.ladder.program import LegacyEncoding

    detail = (
        "CLICK's Syntax Check splits this rung into 2 rungs. Run Syntax Check in CLICK, then "
        "save the project."
    )
    split = LegacyEncoding("main.csv", "Main Program", 2, "", "", detail, True)
    warn = MagicMock()
    monkeypatch.setattr("clicknick.app.messagebox.showwarning", warn)

    _popup_app((split,))._report_legacy_encodings()
    alone = warn.call_args.args[1]
    _popup_app((split, _unreadable(4)))._report_legacy_encodings()
    mixed = warn.call_args.args[1]

    assert alone.endswith(
        f"  Main Program rung 2: {detail}\n\nThe workspace holds an empty rung in place of each."
    )
    assert "Paste" not in alone
    assert "Where a line does not say what to do, paste the rung again" in mixed


def test_a_program_csv_laddercodec_cannot_read_pops_up_too(monkeypatch) -> None:
    from clicknick.ladder.program import LegacyEncoding

    copy = LegacyEncoding("main.csv", "Main Program", None, "", "", "Invalid marker 'X'", True)
    app = _popup_app((copy,))
    warn = MagicMock()
    monkeypatch.setattr("clicknick.app.messagebox.showwarning", warn)

    app._report_legacy_encodings()

    message = warn.call_args.args[1]
    assert message.startswith(
        "ClickNick cannot read these programs in CLICK:\n\n  Main Program: Invalid marker"
    )
    assert message.endswith(
        "Paste them into CLICK again from your own copy, or fix them in CLICK. "
        "Ladder > Compare with > Folder on that copy lists them in red."
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
    app._workspace.review_changes.assert_called_once_with()
