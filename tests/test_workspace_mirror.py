"""Durable active Workspace configuration and migration behavior."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.services.workspace_mirror import (
    ProjectWorkspaceConfig,
    find_project_configs,
    get_workspace_directory_info,
    load_project_workspace_config,
    read_plc_name,
    remember_project_sidecar,
    save_project_workspace_config,
    sync_workspace_to_mirror,
    validate_mirror_destination,
    workspace_path_for_selection,
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


def test_project_sidecar_uses_project_name_and_relative_workspace(tmp_path: Path) -> None:
    project = tmp_path / "Example Project.ckp"
    project.write_text("click", encoding="utf-8")
    workspace = tmp_path / "Example Project Workspace"
    synced = dt.datetime(2026, 8, 28, 12, 30, tzinfo=dt.UTC)
    config = ProjectWorkspaceConfig(project, workspace, synced, plc_name="Line 1")

    sidecar = save_project_workspace_config(config)
    loaded = load_project_workspace_config(sidecar)

    assert sidecar == tmp_path / "Example Project.clicknick.toml"
    assert "active workspace" in sidecar.read_text(encoding="utf-8")
    assert "preserves tests, docs, and tooling" in sidecar.read_text(encoding="utf-8")
    assert 'workspace_path = "Example Project Workspace"' in sidecar.read_text(encoding="utf-8")
    assert 'plc_name = "Line 1"' in sidecar.read_text(encoding="utf-8")
    assert loaded == ProjectWorkspaceConfig(
        project.resolve(), workspace.resolve(), synced, plc_name="Line 1"
    )


def test_project_sidecar_loads_legacy_mirror_path(tmp_path: Path) -> None:
    project = tmp_path / "Legacy.ckp"
    project.write_text("click", encoding="utf-8")
    sidecar = tmp_path / "Legacy.clicknick.toml"
    sidecar.write_text(
        'version = 1\n\n[workspace]\nmirror_path = "Legacy Workspace"\n',
        encoding="utf-8",
    )

    config = load_project_workspace_config(sidecar)

    assert config.project_file == project.resolve()
    assert config.workspace_path == (tmp_path / "Legacy Workspace").resolve()


def test_read_plc_name_from_click_project_ini(tmp_path: Path) -> None:
    project_ini = tmp_path / "Project.ini"
    project_ini.write_text("[Other]\nvalue=1\n[PLCName]\nPLCName=IMHERE\n", encoding="utf-8")

    assert read_plc_name(project_ini) == "IMHERE"
    assert read_plc_name(tmp_path / "missing.ini") is None


def test_workspace_selection_creates_project_named_child_directory(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "LaserBall.ckp"
    desktop = tmp_path / "Desktop"

    assert (
        workspace_path_for_selection(desktop, project)
        == (desktop / "LaserBall Workspace").resolve()
    )


def test_workspace_selection_reuses_matching_workspace_directory(tmp_path: Path) -> None:
    project = tmp_path / "LaserBall.ckp"
    workspace = tmp_path / "laserball workspace"

    assert workspace_path_for_selection(workspace, project) == workspace.resolve()


def test_locator_finds_matching_project_without_duplicating_config(tmp_path: Path) -> None:
    locator = tmp_path / "local" / "project-sidecars.json"
    project = tmp_path / "Machine.ckp"
    project.write_text("click", encoding="utf-8")
    sidecar = save_project_workspace_config(
        ProjectWorkspaceConfig(project, tmp_path / "Machine Workspace")
    )
    remember_project_sidecar(sidecar, locator)
    remember_project_sidecar(sidecar, locator)

    assert find_project_configs("machine.ckp", locator) == [
        ProjectWorkspaceConfig(project.resolve(), (tmp_path / "Machine Workspace").resolve())
    ]
    assert find_project_configs("Other.ckp", locator) == []


def test_plc_name_disambiguates_same_named_projects(tmp_path: Path) -> None:
    locator = tmp_path / "project-sidecars.json"
    configs = []
    for folder, plc_name in (("one", "Mixer"), ("two", "Filler")):
        project = tmp_path / folder / "Machine.ckp"
        project.parent.mkdir()
        project.write_text("click", encoding="utf-8")
        config = ProjectWorkspaceConfig(
            project,
            project.parent / "Machine Workspace",
            plc_name=plc_name,
        )
        configs.append(config)
        remember_project_sidecar(save_project_workspace_config(config), locator)

    matches = find_project_configs("Machine.ckp", locator, plc_name="filler")

    assert len(matches) == 1
    assert matches[0].project_file == configs[1].project_file.resolve()
    assert matches[0].plc_name == "Filler"


def test_sync_overwrites_only_owned_paths_and_never_deletes(tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active", main="proposal\n")
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
    assert (mirror / "src" / "plc" / "main.py").read_text(encoding="utf-8") == ("proposal\n")
    assert (mirror / "csv" / "main.csv").read_text(encoding="utf-8") == "rung\n"
    assert (mirror / "src" / "plc" / "user_module.py").read_text(encoding="utf-8") == ("keep\n")
    assert (mirror / "tests" / "test_smoke.py").read_text(encoding="utf-8") == ("user test\n")
    assert (mirror / "docs" / "new.md").is_file()
    assert (mirror / "notes.md").is_file()
    assert not (mirror / "backup").exists()
    assert not (mirror / ".venv").exists()


def test_sync_rejects_overlapping_workspace_paths(tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active")

    with pytest.raises(ValueError, match="must be separate"):
        sync_workspace_to_mirror(source, source / "mirror")
    with pytest.raises(ValueError, match="must be separate"):
        sync_workspace_to_mirror(source, tmp_path)


def test_destination_validation_can_run_before_sidecar_is_written(tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active")

    with pytest.raises(ValueError, match="must be separate"):
        validate_mirror_destination(source, source / "mirror")

    validate_mirror_destination(source, tmp_path / "durable workspace")


def test_directory_info_reports_generation_and_backup_times(tmp_path: Path) -> None:
    generated = _write_workspace(tmp_path / "active")
    state = generated / "backup" / "generated-source.json"
    state.parent.mkdir()
    state.write_text("{}", encoding="utf-8")
    backup = generated / "backup" / "src" / "plc"
    backup.mkdir(parents=True)
    (backup / "main.py").write_text("proposal\n", encoding="utf-8")
    project = tmp_path / "Example.ckp"
    mirror = tmp_path / "Example Workspace"
    config = ProjectWorkspaceConfig(project, mirror)

    info = get_workspace_directory_info(config, generated)

    assert info.generated_dir == generated.resolve()
    assert info.source_project == project
    assert info.mirror_dir == mirror
    assert info.last_regenerated_at is not None
    assert info.last_backup_at is not None


def test_app_loads_only_unambiguous_project_pairing(monkeypatch, tmp_path: Path) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.connected_click_filename = "Example.ckp"
    app.connected_click_hwnd = None
    app._workspace_config = object()
    app._workspace_mirror_error = "old error"
    config = ProjectWorkspaceConfig(tmp_path / "Example.ckp", tmp_path / "Example Workspace")
    find_configs = MagicMock(return_value=[config])
    monkeypatch.setattr("clicknick.services.workspace_mirror.find_project_configs", find_configs)

    app._load_workspace_pairing()

    find_configs.assert_called_once_with("Example.ckp", plc_name=None)
    assert app._workspace_config == config
    assert app._workspace_mirror_error is None

    find_configs.return_value = [config, config]
    app._load_workspace_pairing()
    assert app._workspace_config is None


def test_setup_creates_project_workspace_inside_selected_location(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "projects" / "LaserBall.ckp"
    project.parent.mkdir()
    project.write_text("click", encoding="utf-8")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    save_config = MagicMock(return_value=project.with_suffix(".clicknick.toml"))
    remember = MagicMock()
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.save_project_workspace_config", save_config
    )
    monkeypatch.setattr("clicknick.services.workspace_mirror.remember_project_sidecar", remember)

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._session = MagicMock()
    app.connected_click_filename = project.name
    app._workspace_config = None
    app._workspace_mirror_error = None
    app._current_plc_name = MagicMock(return_value="IMHERE")
    app._workspace_source_dir = MagicMock(return_value=None)
    app._update_status = MagicMock()
    app._start_analysis_build = MagicMock()
    app.mirror_project_selection_var = MagicMock()
    app.mirror_project_selection_var.get.return_value = str(project)
    app.mirror_location_selection_var = MagicMock()
    workspace = desktop / "LaserBall Workspace"
    app.mirror_location_selection_var.get.return_value = str(workspace)

    app._apply_workspace_mirror_setup()

    assert workspace.is_dir()
    config = save_config.call_args.args[0]
    assert config.project_file == project.resolve()
    assert config.workspace_path == workspace.resolve()
    assert config.plc_name == "IMHERE"
    remember.assert_called_once_with(project.with_suffix(".clicknick.toml"))
    assert app._workspace_config == config
    app._session.use_workspace.assert_called_once_with(workspace)
    app._session.record_rung_stage.assert_called_once_with(0)
    app._start_analysis_build.assert_called_once_with()


def test_browse_mirror_location_previews_named_workspace_without_applying(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "projects" / "LaserBall.ckp"
    project.parent.mkdir()
    project.write_text("click", encoding="utf-8")
    old_mirror = tmp_path / "old" / "LaserBall Workspace"
    new_parent = tmp_path / "new"
    new_parent.mkdir()
    ask_location = MagicMock(return_value=str(new_parent))
    monkeypatch.setattr("clicknick.app.filedialog.askdirectory", ask_location)

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app.mirror_project_selection_var = MagicMock()
    app.mirror_project_selection_var.get.return_value = str(project)
    app.mirror_location_selection_var = MagicMock()
    app.mirror_location_selection_var.get.return_value = str(old_mirror)

    app._select_mirror_location()

    assert ask_location.call_args.kwargs["initialdir"] == old_mirror.parent
    app.mirror_location_selection_var.set.assert_called_once_with(
        str((new_parent / "LaserBall Workspace").resolve())
    )


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
