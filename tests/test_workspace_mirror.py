"""Durable PLC-owned workspace configuration behavior."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.services.workspace_mirror import (
    ProjectWorkspaceConfig,
    find_project_configs,
    get_workspace_directory_info,
    load_project_workspace_config,
    preferred_project_config,
    read_plc_name,
    remember_project_sidecar,
    save_project_workspace_config,
    sidecar_path_for,
    sync_workspace_to_mirror,
    validate_mirror_destination,
    workspace_path_for_selection,
    write_plc_name,
)


def _config(home: Path, plc_name: str = "Line 1") -> ProjectWorkspaceConfig:
    workspace = workspace_path_for_selection(home, plc_name)
    return ProjectWorkspaceConfig(
        plc_name=plc_name,
        workspace_path=workspace,
    )


def _write_workspace(root: Path, main: str = "generated\n") -> Path:
    (root / "src" / "plc").mkdir(parents=True)
    (root / "src" / "plc" / "main.py").write_text(main, encoding="utf-8")
    (root / "csv").mkdir()
    (root / "csv" / "main.csv").write_text("rung\n", encoding="utf-8")
    (root / "nicknames.csv").write_text("nickname\n", encoding="utf-8")
    (root / "project_to_csv.py").write_text("# exporter\n", encoding="utf-8")
    (root / "run.py").write_text("# runner\n", encoding="utf-8")
    return root


def test_workspace_contains_its_own_plc_identity_file(tmp_path: Path) -> None:
    config = _config(tmp_path, "Line 1")

    sidecar = save_project_workspace_config(config)
    loaded = load_project_workspace_config(sidecar)

    assert sidecar == tmp_path / "Line 1 Workspace" / ".clicknick.toml"
    text = sidecar.read_text(encoding="utf-8")
    assert 'name = "Line 1"' in text
    assert "[workspace]" not in text
    assert loaded == config


def test_sidecar_filename_must_match_stored_plc_name(tmp_path: Path) -> None:
    sidecar = tmp_path / "Wrong.clicknick.toml"
    sidecar.write_text(
        'version = 1\n[plc]\nname = "Right"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not a ClickNick project sidecar"):
        load_project_workspace_config(sidecar)


def test_read_and_append_plc_name_preserves_crlf(tmp_path: Path) -> None:
    project_ini = tmp_path / "Project.ini"
    project_ini.write_bytes(b"[Other]\r\nvalue=1\r\n")

    write_plc_name(project_ini, "IMHERE")

    assert read_plc_name(project_ini) == "IMHERE"
    assert project_ini.read_bytes() == (b"[Other]\r\nvalue=1\r\n[PLCName]\r\nPLCName=IMHERE\r\n")


def test_write_plc_name_replaces_existing_value_without_touching_neighbors(
    tmp_path: Path,
) -> None:
    project_ini = tmp_path / "Project.ini"
    project_ini.write_bytes(b"[PLCName]\r\nOther=keep\r\nPLCName=Old\r\n[Next]\r\nValue=1\r\n")

    write_plc_name(project_ini, "New Name")

    assert project_ini.read_bytes() == (
        b"[PLCName]\r\nOther=keep\r\nPLCName=New Name\r\n[Next]\r\nValue=1\r\n"
    )


def test_workspace_selection_uses_plc_name(tmp_path: Path) -> None:
    assert (
        workspace_path_for_selection(tmp_path, "Laser Ball")
        == (tmp_path / "Laser Ball Workspace").resolve()
    )
    assert (
        sidecar_path_for(tmp_path / "Laser Ball Workspace")
        == (tmp_path / "Laser Ball Workspace" / ".clicknick.toml").resolve()
    )


def test_locator_matches_plc_name_regardless_of_project_filename(tmp_path: Path) -> None:
    locator = tmp_path / "local" / "project-sidecars.json"
    config = _config(tmp_path / "home", "Machine")
    sidecar = save_project_workspace_config(config)
    remember_project_sidecar(sidecar, locator)
    remember_project_sidecar(sidecar, locator)

    assert find_project_configs("machine", locator) == [config]
    assert find_project_configs("Other", locator) == []


def test_locator_remembers_explicit_preference_among_matching_workspaces(
    tmp_path: Path,
) -> None:
    locator = tmp_path / "project-sidecars.json"
    first = _config(tmp_path / "one", "Mixer")
    second = _config(tmp_path / "two", "Mixer")
    for config in (first, second):
        remember_project_sidecar(save_project_workspace_config(config), locator)

    matches = find_project_configs("MIXER", locator)
    assert set(matches) == {first, second}
    assert preferred_project_config("Mixer", matches, locator) is None

    remember_project_sidecar(second.sidecar_path, locator, preferred_for="Mixer")

    assert preferred_project_config("mixer", matches, locator) == second
    payload = json.loads(locator.read_text(encoding="utf-8"))
    assert payload["preferred"]["mixer"] == str(second.sidecar_path)


def test_sync_overwrites_only_owned_paths_and_never_deletes(tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active", main="proposal\n")
    (source / ".clicknick.toml").write_text("source identity\n", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "test_smoke.py").write_text("source test\n", encoding="utf-8")
    (source / "docs").mkdir()
    (source / "docs" / "new.md").write_text("new doc\n", encoding="utf-8")
    (source / "backup").mkdir()
    (source / "backup" / "secret.py").write_text("backup\n", encoding="utf-8")
    (source / ".venv").mkdir()
    (source / ".venv" / "marker").write_text("large\n", encoding="utf-8")

    mirror = tmp_path / "Example Workspace"
    (mirror / "src" / "plc").mkdir(parents=True)
    (mirror / "src" / "plc" / "main.py").write_text("old\n", encoding="utf-8")
    (mirror / "src" / "plc" / "user_module.py").write_text("keep\n", encoding="utf-8")
    (mirror / "tests").mkdir()
    (mirror / "tests" / "test_smoke.py").write_text("user test\n", encoding="utf-8")
    (mirror / "notes.md").write_text("keep notes\n", encoding="utf-8")

    result = sync_workspace_to_mirror(source, mirror)

    assert result.mirror_path == mirror.resolve()
    assert result.copied_files >= 6
    assert (mirror / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "proposal\n"
    assert (mirror / "src" / "plc" / "user_module.py").read_text(encoding="utf-8") == "keep\n"
    assert (mirror / "tests" / "test_smoke.py").read_text(encoding="utf-8") == "user test\n"
    assert (mirror / "docs" / "new.md").is_file()
    assert (mirror / "notes.md").is_file()
    assert not (mirror / "backup").exists()
    assert not (mirror / ".venv").exists()
    assert not (mirror / ".clicknick.toml").exists()


def test_sync_rejects_overlapping_workspace_paths(tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active")

    with pytest.raises(ValueError, match="must be separate"):
        sync_workspace_to_mirror(source, source / "mirror")
    with pytest.raises(ValueError, match="must be separate"):
        sync_workspace_to_mirror(source, tmp_path)
    validate_mirror_destination(source, tmp_path / "durable workspace")


def test_directory_info_reports_configuration_and_generation_times(tmp_path: Path) -> None:
    generated = _write_workspace(tmp_path / "active")
    state = generated / "backup" / "generated-source.json"
    state.parent.mkdir()
    state.write_text("{}", encoding="utf-8")
    backup = generated / "backup" / "src" / "plc"
    backup.mkdir(parents=True)
    (backup / "main.py").write_text("proposal\n", encoding="utf-8")
    config = _config(tmp_path, "Example")

    info = get_workspace_directory_info(config, generated)

    assert info.generated_dir == generated.resolve()
    assert info.config_path == config.sidecar_path
    assert info.mirror_dir == config.workspace_path
    assert info.last_regenerated_at is not None
    assert info.last_backup_at is not None


def test_app_loads_one_matching_plc_workspace(monkeypatch, tmp_path: Path) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.connected_click_filename = "Machine-20260829.ckp"
    app._mirror_setup_window = None
    app._workspace_config = object()
    app._workspace_mirror_error = "old error"
    app._current_plc_name = MagicMock(return_value="Machine")
    app._refresh_workspace_ui = MagicMock()
    config = _config(tmp_path, "Machine")
    config.workspace_path.mkdir(parents=True)
    find_configs = MagicMock(return_value=[config])
    monkeypatch.setattr("clicknick.services.workspace_mirror.find_project_configs", find_configs)

    app._load_workspace_pairing()

    find_configs.assert_called_once_with("Machine")
    assert app._workspace_config == config
    assert app._workspace_mirror_error is None


def test_app_reports_a_missing_matched_workspace(monkeypatch, tmp_path: Path) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._mirror_setup_window = None
    app._workspace_config = None
    app._workspace_mirror_error = None
    app._current_plc_name = MagicMock(return_value="Machine")
    app._refresh_workspace_ui = MagicMock()
    config = _config(tmp_path, "Machine")
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.find_project_configs",
        MagicMock(return_value=[config]),
    )

    app._load_workspace_pairing()

    assert app._workspace_config is None
    assert str(config.workspace_path) in app._workspace_mirror_error


def test_app_requires_a_choice_for_unpreferred_duplicate_matches(
    monkeypatch, tmp_path: Path
) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._mirror_setup_window = None
    app._workspace_config = None
    app._workspace_mirror_error = None
    app._current_plc_name = MagicMock(return_value="Machine")
    app._refresh_workspace_ui = MagicMock()
    matches = [_config(tmp_path / "one", "Machine"), _config(tmp_path / "two", "Machine")]
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.find_project_configs", MagicMock(return_value=matches)
    )
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.preferred_project_config",
        MagicMock(return_value=None),
    )

    app._load_workspace_pairing()

    assert app._workspace_config is None
    assert app._workspace_matches == matches
    assert "Multiple workspaces" in app._workspace_mirror_error


def test_setup_creates_plc_named_workspace_and_remembers_preference(
    monkeypatch, tmp_path: Path
) -> None:
    config = _config(tmp_path / "Desktop", "IMHERE")
    save_config = MagicMock(return_value=config.sidecar_path)
    remember = MagicMock()
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.save_project_workspace_config", save_config
    )
    monkeypatch.setattr("clicknick.services.workspace_mirror.remember_project_sidecar", remember)

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._session = MagicMock()
    app._workspace_config = None
    app._workspace_matches = []
    app._pending_workspace_config = config
    app._workspace_mirror_error = None
    app._mirror_setup_window = None
    app._ensure_plc_name_for_workspace = MagicMock(return_value="IMHERE")
    app._workspace_source_dir = MagicMock(return_value=None)
    app._update_status = MagicMock()
    app._start_analysis_build = MagicMock()
    app.mirror_project_selection_var = MagicMock()
    app.mirror_location_selection_var = MagicMock()
    app.workspace_setup_action_var = MagicMock()

    app._apply_workspace_mirror_setup()

    assert config.workspace_path.is_dir()
    save_config.assert_called_once_with(config)
    remember.assert_called_once_with(config.sidecar_path, preferred_for="IMHERE")
    assert app._workspace_config == config
    app._session.use_workspace.assert_called_once_with(config.workspace_path)
    app._session.record_rung_stage.assert_called_once_with(0)
    app._start_analysis_build.assert_called_once_with()


def test_choose_new_home_previews_plc_named_paths(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "workspaces"
    home.mkdir()
    monkeypatch.setattr("clicknick.app.filedialog.askdirectory", MagicMock(return_value=str(home)))

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._mirror_setup_window = None
    app._pending_workspace_config = None
    app._workspace_matches = []
    app._ensure_plc_name_for_workspace = MagicMock(return_value="LaserBall")
    app.mirror_project_selection_var = MagicMock()
    app.mirror_location_selection_var = MagicMock()
    app.workspace_setup_action_var = MagicMock()

    app._select_mirror_location()

    assert app._pending_workspace_config == _config(home, "LaserBall")
    app.mirror_project_selection_var.set.assert_called_once_with("")
    app.mirror_location_selection_var.set.assert_called_once_with(str(home / "LaserBall Workspace"))
    app.workspace_setup_action_var.set.assert_called_once_with("Create Workspace")


def test_find_existing_workspace_selects_a_folder_not_a_config_file(
    monkeypatch, tmp_path: Path
) -> None:
    config = _config(tmp_path, "LaserBall")
    save_project_workspace_config(config)
    monkeypatch.setattr(
        "clicknick.app.filedialog.askdirectory",
        MagicMock(return_value=str(config.workspace_path)),
    )

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._mirror_setup_window = None
    app._pending_workspace_config = None
    app._workspace_matches = []
    app._ensure_plc_name_for_workspace = MagicMock(return_value="LaserBall")
    app.mirror_project_selection_var = MagicMock()
    app.mirror_location_selection_var = MagicMock()
    app.workspace_setup_action_var = MagicMock()

    app._select_existing_workspace_config()

    assert app._pending_workspace_config == config
    app.mirror_project_selection_var.set.assert_called_once_with(str(config.workspace_path))
    app.mirror_location_selection_var.set.assert_called_once_with("")
    app.workspace_setup_action_var.set.assert_called_once_with("Use Workspace")


def test_workspace_setup_prompts_for_and_writes_a_missing_plc_name(monkeypatch) -> None:
    ask_name = MagicMock(side_effect=["Bad.Name", "  Line 1  "])
    write_name = MagicMock()
    monkeypatch.setattr("clicknick.app.simpledialog.askstring", ask_name)
    monkeypatch.setattr("clicknick.app.messagebox.showerror", MagicMock())
    monkeypatch.setattr("clicknick.app.messagebox.showinfo", MagicMock())
    monkeypatch.setattr("clicknick.services.workspace_mirror.write_plc_name", write_name)
    monkeypatch.setattr(
        "clicknick.live.session.click_temp_dir", MagicMock(return_value=Path("CLICK-temp"))
    )

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._session = object()
    app.connected_click_hwnd = 123
    app._mirror_setup_window = None
    app._current_plc_name = MagicMock(return_value=None)
    app._update_status = MagicMock()
    app.plc_name_var = MagicMock()

    assert app._ensure_plc_name_for_workspace() == "Line 1"
    assert ask_name.call_count == 2
    write_name.assert_called_once_with(Path("CLICK-temp") / "Project.ini", "Line 1")
    app.plc_name_var.set.assert_called_once_with("Line 1")


def test_open_workspace_uses_single_active_folder(tmp_path: Path) -> None:
    workspace = tmp_path / "LaserBall Workspace"
    app = ClickNickApp.__new__(ClickNickApp)
    app._workspace_display_dir = MagicMock(return_value=workspace)
    app._open_folder = MagicMock()

    app._open_workspace()

    app._open_folder.assert_called_once_with(
        workspace,
        title="Open Workspace",
        unavailable="Workspace is not available",
    )
