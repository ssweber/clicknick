"""One-way durable Workspace mirror behavior."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from clicknick.app import ClickNickApp
from clicknick.services.workspace_mirror import (
    MirrorState,
    ProjectWorkspaceConfig,
    find_project_configs,
    get_mirror_status,
    get_workspace_directory_info,
    load_project_workspace_config,
    mirror_path_for_selection,
    read_plc_name,
    record_successful_sync,
    remember_project_sidecar,
    save_project_workspace_config,
    sync_workspace_to_mirror,
    validate_mirror_destination,
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


def test_project_sidecar_uses_project_name_and_relative_mirror(tmp_path: Path) -> None:
    project = tmp_path / "Example Project.ckp"
    project.write_text("click", encoding="utf-8")
    mirror = tmp_path / "Example Project Workspace"
    synced = dt.datetime(2026, 8, 28, 12, 30, tzinfo=dt.UTC)
    config = ProjectWorkspaceConfig(project, mirror, synced, plc_name="Line 1")

    sidecar = save_project_workspace_config(config)
    loaded = load_project_workspace_config(sidecar)

    assert sidecar == tmp_path / "Example Project.clicknick.toml"
    assert "generated ClickNick workspace -> mirror" in sidecar.read_text(encoding="utf-8")
    assert "Sync never deletes files" in sidecar.read_text(encoding="utf-8")
    assert 'mirror_path = "Example Project Workspace"' in sidecar.read_text(encoding="utf-8")
    assert 'plc_name = "Line 1"' in sidecar.read_text(encoding="utf-8")
    assert loaded == ProjectWorkspaceConfig(
        project.resolve(), mirror.resolve(), synced, plc_name="Line 1"
    )


def test_read_plc_name_from_click_project_ini(tmp_path: Path) -> None:
    project_ini = tmp_path / "Project.ini"
    project_ini.write_text("[Other]\nvalue=1\n[PLCName]\nPLCName=IMHERE\n", encoding="utf-8")

    assert read_plc_name(project_ini) == "IMHERE"
    assert read_plc_name(tmp_path / "missing.ini") is None


def test_mirror_selection_creates_project_named_child_directory(tmp_path: Path) -> None:
    project = tmp_path / "projects" / "LaserBall.ckp"
    desktop = tmp_path / "Desktop"

    assert (
        mirror_path_for_selection(desktop, project) == (desktop / "LaserBall Workspace").resolve()
    )


def test_mirror_selection_reuses_matching_workspace_directory(tmp_path: Path) -> None:
    project = tmp_path / "LaserBall.ckp"
    workspace = tmp_path / "laserball workspace"

    assert mirror_path_for_selection(workspace, project) == workspace.resolve()


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


def test_mirror_status_detects_owned_file_drift(tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active")
    mirror = tmp_path / "mirror"
    result = sync_workspace_to_mirror(source, mirror)
    project = tmp_path / "Example.ckp"
    project.write_text("click", encoding="utf-8")
    config = ProjectWorkspaceConfig(project, mirror, result.synced_at)

    status = get_mirror_status(config, source)
    assert status.state is MirrorState.SYNCED
    assert status.label == "Synced"

    (source / "src" / "plc" / "main.py").write_text("changed\n", encoding="utf-8")
    status = get_mirror_status(config, source)
    assert status.state is MirrorState.PAIRED
    assert status.label == "Paired"


def test_successful_sync_timestamp_is_saved_in_sidecar(tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active")
    mirror = tmp_path / "mirror"
    project = tmp_path / "Example.ckp"
    project.write_text("click", encoding="utf-8")
    config = ProjectWorkspaceConfig(project, mirror)

    updated = record_successful_sync(config, sync_workspace_to_mirror(source, mirror))

    assert updated.last_synced_at is not None
    assert load_project_workspace_config(updated.sidecar_path) == updated


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


def test_app_syncs_workspace_and_persists_success(monkeypatch, tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active")
    config = ProjectWorkspaceConfig(tmp_path / "Example.ckp", tmp_path / "mirror")
    synced = dt.datetime(2026, 8, 28, 14, 0, tzinfo=dt.UTC)
    result = SimpleNamespace(copied_files=6, mirror_path=config.mirror_path, synced_at=synced)
    updated = ProjectWorkspaceConfig(config.project_file, config.mirror_path, synced)
    sync = MagicMock(return_value=result)
    record = MagicMock(return_value=updated)
    monkeypatch.setattr("clicknick.services.workspace_mirror.sync_workspace_to_mirror", sync)
    monkeypatch.setattr("clicknick.services.workspace_mirror.record_successful_sync", record)

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._workspace_config = config
    app._workspace_mirror_error = "old error"
    app._workspace_source_dir = MagicMock(return_value=source)
    app._update_status = MagicMock()

    app._sync_workspace_mirror()

    sync.assert_called_once_with(source, config.mirror_path)
    record.assert_called_once_with(config, result)
    assert app._workspace_config == updated
    assert app._workspace_mirror_error is None
    app._update_status.assert_called_once_with(
        f"Workspace mirror synced (6 files): {config.mirror_path}", "connected"
    )


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
    monkeypatch.setattr("clicknick.app.filedialog.askopenfilename", lambda **_kwargs: str(project))
    monkeypatch.setattr("clicknick.app.filedialog.askdirectory", lambda **_kwargs: str(desktop))
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.save_project_workspace_config", save_config
    )
    monkeypatch.setattr("clicknick.services.workspace_mirror.remember_project_sidecar", remember)

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._session = object()
    app.connected_click_filename = project.name
    app._workspace_config = None
    app._workspace_mirror_error = None
    app._current_plc_name = MagicMock(return_value="IMHERE")
    app._workspace_source_dir = MagicMock(return_value=None)
    app._update_status = MagicMock()
    app._refresh_workspace_ui = MagicMock()

    app._setup_workspace_mirror()

    workspace = desktop / "LaserBall Workspace"
    assert workspace.is_dir()
    config = save_config.call_args.args[0]
    assert config.project_file == project
    assert config.mirror_path == workspace.resolve()
    assert config.plc_name == "IMHERE"
    remember.assert_called_once_with(project.with_suffix(".clicknick.toml"))
    assert app._workspace_config == config


def test_change_mirror_reuses_known_project_after_explicit_action(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "projects" / "LaserBall.ckp"
    project.parent.mkdir()
    project.write_text("click", encoding="utf-8")
    old_mirror = tmp_path / "old" / "LaserBall Workspace"
    new_parent = tmp_path / "new"
    new_parent.mkdir()
    ask_project = MagicMock()
    ask_location = MagicMock(return_value=str(new_parent))
    save_config = MagicMock(return_value=project.with_suffix(".clicknick.toml"))
    monkeypatch.setattr("clicknick.app.filedialog.askopenfilename", ask_project)
    monkeypatch.setattr("clicknick.app.filedialog.askdirectory", ask_location)
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.save_project_workspace_config", save_config
    )
    monkeypatch.setattr("clicknick.services.workspace_mirror.remember_project_sidecar", MagicMock())

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._session = object()
    app.connected_click_filename = project.name
    app._workspace_config = ProjectWorkspaceConfig(project, old_mirror)
    app._workspace_mirror_error = None
    app._current_plc_name = MagicMock(return_value="IMHERE")
    app._workspace_source_dir = MagicMock(return_value=None)
    app._update_status = MagicMock()
    app._refresh_workspace_ui = MagicMock()

    app._setup_workspace_mirror()

    ask_project.assert_not_called()
    assert ask_location.call_args.kwargs["initialdir"] == old_mirror.parent
    config = save_config.call_args.args[0]
    assert config.project_file == project
    assert config.mirror_path == (new_parent / "LaserBall Workspace").resolve()


def test_explicit_open_actions_do_not_conflate_generated_and_mirror_folders(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "active"
    mirror = tmp_path / "LaserBall Workspace"
    app = ClickNickApp.__new__(ClickNickApp)
    app._workspace_config = ProjectWorkspaceConfig(tmp_path / "LaserBall.ckp", mirror)
    app._workspace_source_dir = MagicMock(return_value=generated)
    app._open_folder = MagicMock()

    app._open_generated_workspace()
    app._open_mirror_folder()

    assert app._open_folder.call_args_list == [
        call(
            generated,
            title="Open Generated Workspace",
            unavailable="Generated workspace is not available",
        ),
        call(
            mirror,
            title="Open Mirror Folder",
            unavailable="Workspace mirror is not configured",
        ),
    ]


def test_app_surfaces_workspace_sync_failure(monkeypatch, tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active")
    config = ProjectWorkspaceConfig(tmp_path / "Example.ckp", tmp_path / "mirror")
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.sync_workspace_to_mirror",
        MagicMock(side_effect=OSError("disk unavailable")),
    )
    showerror = MagicMock()
    monkeypatch.setattr("clicknick.app.messagebox.showerror", showerror)

    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._workspace_config = config
    app._workspace_mirror_error = None
    app._workspace_source_dir = MagicMock(return_value=source)
    app._update_status = MagicMock()

    app._sync_workspace_mirror()

    assert app._workspace_mirror_error == "disk unavailable"
    showerror.assert_called_once_with("Sync Workspace Mirror", "disk unavailable", parent=app.root)
    app._update_status.assert_called_once_with(
        "Workspace mirror sync failed: disk unavailable", "error"
    )
