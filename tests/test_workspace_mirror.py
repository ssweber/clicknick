"""Durable PLC-owned workspace configuration behavior."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.connection_controller import ConnectionController
from clicknick.connection_session import ClickConnection, ConnectionSession
from clicknick.services.analysis_service import _publish_generated_project
from clicknick.services.project_workspace import (
    backup_plc_source,
    older_plc_backups,
    plc_backup_time,
    plc_source_is_modified,
    record_generated_plc_source,
)
from clicknick.services.workspace_mirror import (
    ProjectWorkspaceConfig,
    WorkspacePairing,
    find_project_configs,
    get_workspace_directory_info,
    load_project_workspace_config,
    preferred_project_config,
    remember_project_sidecar,
    save_project_workspace_config,
    sidecar_path_for,
    sync_workspace_to_mirror,
    validate_mirror_destination,
    workspace_path_for_selection,
)
from clicknick.workspace_controller import WorkspaceController


def _app(session) -> ClickNickApp:
    """An app connected through *session* (or none), its Workspace setup form mocked."""
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app.root = MagicMock()
    app._session = session
    app._update_status = MagicMock()
    app._start_analysis_build = MagicMock()
    app.plc_name_var = MagicMock()
    app.mirror_project_selection_var = MagicMock()
    app.mirror_location_selection_var = MagicMock()
    app.workspace_setup_action_var = MagicMock()
    app._workspace = WorkspaceController(app)
    return app


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


# Project.ini as CLICK writes it: CLICK 3 keeps the PLC name in [PLCName], CLICK 4 in
# [Sec20] Key1; both write the line, empty when the PLC has no name.
_PROJECT_INI_NAMES = [
    pytest.param(b"[PLCName]\r\nPLCName=Line 1\r\n[Next]\r\nValue=1\r\n", "Line 1", id="click3"),
    pytest.param(
        b"[Sec21]\r\nKey1=1\r\n[Sec20]\r\nKey1=AutoDayTankFill\r\n[Sec22]\r\n",
        "AutoDayTankFill",
        id="click4",
    ),
    pytest.param(b"[Sec21]\r\nKey1=1\r\n[Sec20]\r\nKey1=\r\n", None, id="click4-unnamed"),
    # CLICK 4 shows the [Sec20] name over a [PLCName] another tool added
    pytest.param(
        b"[PLCName]\r\nPLCName=Old\r\n[Sec21]\r\nKey1=1\r\n[Sec20]\r\nKey1=New\r\n",
        "New",
        id="click4-stray-plcname",
    ),
    pytest.param(b"PLCName=Line 1\r\n", None, id="no-section-header"),
    pytest.param(b"[PLCName]\r\nPLCName=\xff\xfe\r\n", None, id="not-utf8"),
    pytest.param(None, None, id="missing"),
]


def _click_temp(monkeypatch, tmp_path: Path, project_ini: bytes | None) -> None:
    if project_ini is not None:
        (tmp_path / "Project.ini").write_bytes(project_ini)
    monkeypatch.setattr(
        "clicknick.utils.click_temp.click_temp_dir", MagicMock(return_value=tmp_path)
    )


@pytest.mark.parametrize(("project_ini", "expected"), _PROJECT_INI_NAMES)
def test_current_plc_name_reads_click_3_and_4_project_ini(
    monkeypatch, tmp_path: Path, project_ini: bytes | None, expected: str | None
) -> None:
    _click_temp(monkeypatch, tmp_path, project_ini)
    app = _app(ConnectionSession(ClickConnection("1", 123, "Example.ckp")))

    assert app._workspace.plc_name() == expected


@pytest.mark.parametrize(("project_ini", "expected"), _PROJECT_INI_NAMES)
def test_simulation_key_is_the_plc_name_else_the_project_name(
    monkeypatch, tmp_path: Path, project_ini: bytes | None, expected: str | None
) -> None:
    _click_temp(monkeypatch, tmp_path, project_ini)
    session = ConnectionSession(ClickConnection("1", 123, "Example.ckp"))

    assert session._simulation_key() == (expected or "Example")


def test_workspace_setup_writes_the_plc_name_where_click_4_reads_it(
    monkeypatch, tmp_path: Path
) -> None:
    project_ini = b"[Sec21]\r\nKey1=1\r\n[Sec20]\r\nKey1=\r\n[Sec22]\r\n"
    _click_temp(monkeypatch, tmp_path, project_ini)
    monkeypatch.setattr(
        "clicknick.workspace_controller.simpledialog.askstring", MagicMock(return_value="Line 1")
    )
    monkeypatch.setattr("clicknick.workspace_controller.messagebox.showinfo", MagicMock())
    app = _app(ConnectionSession(ClickConnection("1", 123, "Example.ckp"), has_database=True))

    assert app._workspace._ensure_plc_name() == "Line 1"
    assert (tmp_path / "Project.ini").read_bytes() == (
        b"[Sec21]\r\nKey1=1\r\n[Sec20]\r\nKey1=Line 1\r\n[Sec22]\r\n"
    )
    assert app._workspace.plc_name() == "Line 1"


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
    record_generated_plc_source(mirror)
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
    assert not (mirror / "backup" / "secret.py").exists()
    assert not (mirror / "backup" / "src").exists()
    assert not (mirror / ".venv").exists()
    assert not (mirror / ".clicknick.toml").exists()


def test_keeping_a_mirrors_edited_source_keeps_its_earlier_backup(tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active", main="generated\n")
    record_generated_plc_source(source)
    mirror = _write_workspace(tmp_path / "Example Workspace", main="generated\n")
    record_generated_plc_source(mirror)
    earlier = mirror / "backup" / "src" / "plc"
    earlier.mkdir(parents=True)
    (earlier / "main.py").write_text("earlier edits\n", encoding="utf-8")
    (mirror / "src" / "plc" / "main.py").write_text("unpasted edits\n", encoding="utf-8")

    result = sync_workspace_to_mirror(source, mirror)

    assert result.kept_source
    assert (earlier / "main.py").read_text(encoding="utf-8") == "unpasted edits\n"
    (older,) = older_plc_backups(mirror)
    older_main = mirror / "backup" / "older" / older / "src" / "plc" / "main.py"
    assert older_main.read_text(encoding="utf-8") == "earlier edits\n"

    sync_workspace_to_mirror(source, mirror)

    assert older_plc_backups(mirror) == [older]


def _generated(root: Path, main: str) -> Path:
    (root / "src" / "plc").mkdir(parents=True)
    (root / "src" / "plc" / "main.py").write_text(main, encoding="utf-8")
    (root / "project_to_csv.py").write_text("# exporter\n", encoding="utf-8")
    return root


def _choose_existing_workspace(
    monkeypatch,
    source: Path,
    mirror: Path,
    analysis: object | None = None,
    ensure_plc_name: MagicMock | None = None,
) -> MagicMock:
    """Pick *mirror* in Workspace setup while *source* is the active workspace.

    *analysis* is the connection's analysis, if it matters; *ensure_plc_name*
    stands in for asking the PLC name. Returns the mocked messagebox.showerror.
    """
    monkeypatch.setattr("clicknick.services.workspace_mirror.remember_project_sidecar", MagicMock())
    monkeypatch.setattr(
        "clicknick.workspace_controller.messagebox.askokcancel", MagicMock(return_value=True)
    )
    showerror = MagicMock()
    monkeypatch.setattr("clicknick.workspace_controller.messagebox.showerror", showerror)

    app = _app(
        MagicMock(
            pairing=WorkspacePairing(),
            setup_window=None,
            pending_workspace=ProjectWorkspaceConfig("Line1", mirror),
        )
    )
    if analysis is not None:
        app._session.analysis = analysis
    workspace = app._workspace
    workspace._ensure_plc_name = ensure_plc_name or MagicMock(return_value="Line1")
    workspace.source_dir = MagicMock(return_value=source)

    workspace._apply_setup()
    return showerror


def test_choosing_an_existing_workspace_keeps_its_edited_source(
    monkeypatch, tmp_path: Path
) -> None:
    durable = tmp_path / "Line1 Workspace"
    _publish_generated_project(_generated(tmp_path / "g0", "generated A\n"), durable)
    (durable / "src" / "plc" / "main.py").write_text("unpasted edits\n", encoding="utf-8")
    (durable / "src" / "plc" / "user_module.py").write_text("helper\n", encoding="utf-8")
    temporary = tmp_path / "pyrung_project"
    _publish_generated_project(_generated(tmp_path / "g1", "generated B\n"), temporary)

    showerror = _choose_existing_workspace(monkeypatch, temporary, durable)

    showerror.assert_not_called()
    assert (durable / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "unpasted edits\n"
    # The build that follows regenerates src/plc; the edits stay in the backup.
    _publish_generated_project(_generated(tmp_path / "g2", "generated B\n"), durable)
    backup = durable / "backup" / "src" / "plc"
    assert (backup / "main.py").read_text(encoding="utf-8") == "unpasted edits\n"
    assert (backup / "user_module.py").read_text(encoding="utf-8") == "helper\n"


def test_a_chosen_workspace_whose_edited_source_was_kept_shows_as_edited(
    monkeypatch, tmp_path: Path
) -> None:
    durable = tmp_path / "Line1 Workspace"
    _publish_generated_project(_generated(tmp_path / "g0", "generated A\n"), durable)
    (durable / "src" / "plc" / "main.py").write_text("unpasted edits\n", encoding="utf-8")
    temporary = tmp_path / "pyrung_project"
    _publish_generated_project(_generated(tmp_path / "g1", "generated B\n"), temporary)
    assert not plc_source_is_modified(temporary)

    _choose_existing_workspace(monkeypatch, temporary, durable)

    assert (durable / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "unpasted edits\n"
    assert plc_source_is_modified(durable)


def _failed_build() -> object:
    from types import SimpleNamespace

    from clicknick.services.analysis_service import AnalysisStatus

    return SimpleNamespace(
        status=AnalysisStatus.FAILED, project_is_current=False, error="ValueError: bad rung"
    )


def test_setup_refuses_an_earlier_saves_workspace_after_a_failed_build(
    monkeypatch, tmp_path: Path
) -> None:
    temporary = tmp_path / "pyrung_project"
    _publish_generated_project(_generated(tmp_path / "g1", "earlier save\n"), temporary)
    durable = tmp_path / "Line1 Workspace"

    showerror = _choose_existing_workspace(monkeypatch, temporary, durable, _failed_build())

    message = showerror.call_args.args[1]
    assert "could not be built from CLICK's last save" in message
    assert "ValueError: bad rung" in message
    assert not durable.exists()


def test_setup_refused_after_a_failed_build_asks_no_plc_name(monkeypatch, tmp_path: Path) -> None:
    """The PLC name is written into CLICK's folder, so it is not asked for a refused setup."""
    temporary = tmp_path / "pyrung_project"
    _publish_generated_project(_generated(tmp_path / "g1", "earlier save\n"), temporary)
    ensure_plc_name = MagicMock(return_value="Line1")

    showerror = _choose_existing_workspace(
        monkeypatch, temporary, tmp_path / "Line1 Workspace", _failed_build(), ensure_plc_name
    )

    showerror.assert_called_once()
    ensure_plc_name.assert_not_called()


def test_setup_of_the_active_workspace_after_a_failed_build_copies_nothing_and_is_not_refused(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "Line1 Workspace"
    _publish_generated_project(_generated(tmp_path / "g1", "earlier save\n"), workspace)

    showerror = _choose_existing_workspace(monkeypatch, workspace, workspace, _failed_build())

    showerror.assert_not_called()
    assert sidecar_path_for(workspace).is_file()


def test_choosing_an_unedited_workspace_takes_the_active_source(
    monkeypatch, tmp_path: Path
) -> None:
    durable = tmp_path / "Line1 Workspace"
    _publish_generated_project(_generated(tmp_path / "g0", "generated A\n"), durable)
    temporary = tmp_path / "pyrung_project"
    _publish_generated_project(_generated(tmp_path / "g1", "generated B\n"), temporary)
    (temporary / "src" / "plc" / "main.py").write_text("agent edits\n", encoding="utf-8")

    showerror = _choose_existing_workspace(monkeypatch, temporary, durable)

    showerror.assert_not_called()
    assert (durable / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "agent edits\n"
    assert not (durable / "backup" / "src" / "plc").exists()
    assert plc_source_is_modified(durable)


def test_choosing_an_edited_workspace_while_the_active_one_is_edited_changes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    durable = tmp_path / "Line1 Workspace"
    _publish_generated_project(_generated(tmp_path / "g0", "generated A\n"), durable)
    (durable / "src" / "plc" / "main.py").write_text("durable edits\n", encoding="utf-8")
    temporary = tmp_path / "pyrung_project"
    _publish_generated_project(_generated(tmp_path / "g1", "generated B\n"), temporary)
    (temporary / "src" / "plc" / "main.py").write_text("temporary edits\n", encoding="utf-8")
    before = sorted(path.relative_to(durable) for path in durable.rglob("*"))

    showerror = _choose_existing_workspace(monkeypatch, temporary, durable)

    message = showerror.call_args.args[1]
    assert str(durable.resolve() / "src" / "plc") in message
    assert str(temporary.resolve() / "src" / "plc") in message
    assert "Paste or discard" in message
    assert sorted(path.relative_to(durable) for path in durable.rglob("*")) == before
    assert (durable / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "durable edits\n"
    assert plc_source_is_modified(durable)


def test_sync_records_a_mirror_that_took_an_unedited_source_as_that_generation(
    tmp_path: Path,
) -> None:
    """Read and recorded while the sync holds the workspaces, not around it."""
    source = _write_workspace(tmp_path / "active", main="generated\n")
    record_generated_plc_source(source)
    sync_workspace_to_mirror(source, tmp_path / "Clean Workspace")
    assert not plc_source_is_modified(tmp_path / "Clean Workspace")

    (source / "src" / "plc" / "main.py").write_text("agent edits\n", encoding="utf-8")
    sync_workspace_to_mirror(source, tmp_path / "Edited Workspace")
    assert plc_source_is_modified(tmp_path / "Edited Workspace")


def test_sync_says_when_it_kept_the_mirrors_edited_source(tmp_path: Path) -> None:
    source = _write_workspace(tmp_path / "active", main="proposal\n")
    record_generated_plc_source(source)
    clean = _write_workspace(tmp_path / "Clean Workspace")
    record_generated_plc_source(clean)
    edited = _write_workspace(tmp_path / "Edited Workspace", main="edits\n")

    assert not sync_workspace_to_mirror(source, clean).kept_source
    assert sync_workspace_to_mirror(source, edited).kept_source
    assert sync_workspace_to_mirror(source, tmp_path / "New Workspace").kept_source is False


@pytest.mark.parametrize("content", ["[]", "null", '"sidecars"', "[1, 2]"])
def test_a_locator_that_is_not_an_object_reads_as_empty(tmp_path: Path, content: str) -> None:
    locator = tmp_path / "project-sidecars.json"
    locator.write_text(content, encoding="utf-8")
    config = _config(tmp_path / "home", "Machine")
    sidecar = save_project_workspace_config(config)

    assert find_project_configs("Machine", locator) == []
    assert preferred_project_config("Machine", [config], locator) is None
    remember_project_sidecar(sidecar, locator, preferred_for="Machine")
    assert find_project_configs("Machine", locator) == [config]


def test_sync_removes_the_mirrors_legacy_record_once_the_workspace_has_none(
    tmp_path: Path,
) -> None:
    source = _write_workspace(tmp_path / "active")
    record_generated_plc_source(source)
    record = Path("csv") / "legacy_encodings.json"
    (source / record).write_text("[]", encoding="utf-8")
    mirror = tmp_path / "Example Workspace"
    sync_workspace_to_mirror(source, mirror)
    assert (mirror / record).is_file()
    (mirror / "csv" / "user.txt").write_text("keep\n", encoding="utf-8")

    # CLICK saved a clean copy
    (source / record).unlink()
    sync_workspace_to_mirror(source, mirror)

    assert not (mirror / record).exists()
    assert (mirror / "csv" / "main.csv").is_file()
    assert (mirror / "csv" / "user.txt").is_file()  # Nothing else is removed


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

    # A backup made now reports when it was made, not when its files were last edited.
    os.utime(generated / "src" / "plc" / "main.py", (0, 0))
    backup_plc_source(generated)
    taken = plc_backup_time(generated)
    assert taken is not None and taken.year > 1970
    assert get_workspace_directory_info(config, generated).last_backup_at == taken


def _machine_session(monkeypatch) -> ConnectionSession:
    """A session on a project whose PLC is named Machine."""
    session = ConnectionSession(ClickConnection("1", 2, "Machine-20260829.ckp"))
    monkeypatch.setattr(session, "plc_name", lambda: "Machine")
    return session


def test_session_pairs_one_matching_plc_workspace(monkeypatch, tmp_path: Path) -> None:
    session = _machine_session(monkeypatch)
    config = _config(tmp_path, "Machine")
    config.workspace_path.mkdir(parents=True)
    find_configs = MagicMock(return_value=[config])
    monkeypatch.setattr("clicknick.services.workspace_mirror.find_project_configs", find_configs)

    session.load_workspace_pairing()

    find_configs.assert_called_once_with("Machine")
    assert session.pairing == WorkspacePairing(config, [config])
    assert session.workspace_dir == config.workspace_path.resolve()


def test_session_reports_a_missing_matched_workspace(monkeypatch, tmp_path: Path) -> None:
    session = _machine_session(monkeypatch)
    config = _config(tmp_path, "Machine")
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.find_project_configs",
        MagicMock(return_value=[config]),
    )

    session.load_workspace_pairing()

    assert session.pairing.config is None and session.workspace_dir is None
    assert str(config.workspace_path) in session.pairing.error


def test_session_requires_a_choice_for_unpreferred_duplicate_matches(
    monkeypatch, tmp_path: Path
) -> None:
    session = _machine_session(monkeypatch)
    matches = [_config(tmp_path / "one", "Machine"), _config(tmp_path / "two", "Machine")]
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.find_project_configs", MagicMock(return_value=matches)
    )
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.preferred_project_config",
        MagicMock(return_value=None),
    )

    session.load_workspace_pairing()

    assert session.pairing.config is None
    assert session.pairing.matches == matches
    assert "Multiple workspaces" in session.pairing.error


def test_a_new_session_pairs_its_own_plc(monkeypatch, tmp_path: Path) -> None:
    config = _config(tmp_path, "Machine")
    config.workspace_path.mkdir(parents=True)
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.find_project_configs",
        MagicMock(return_value=[config]),
    )
    monkeypatch.setattr(ConnectionSession, "plc_name", lambda _self: "Machine")
    app = _app(None)

    ConnectionController(app)._open_connection_session(
        ClickConnection("1", 2, "Machine-20260829.ckp")
    )

    assert app._session.pairing.config == config
    assert app._workspace.configured_dir() == config.workspace_path


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

    app = _app(MagicMock(pairing=WorkspacePairing(), setup_window=None, pending_workspace=config))
    app._workspace._ensure_plc_name = MagicMock(return_value="IMHERE")
    app._workspace.source_dir = MagicMock(return_value=None)

    app._workspace._apply_setup()

    assert config.workspace_path.is_dir()
    save_config.assert_called_once_with(config)
    remember.assert_called_once_with(config.sidecar_path, preferred_for="IMHERE")
    app._session.use_workspace.assert_called_once_with(config)
    app._session.record_rung_stage.assert_called_once_with(0)
    app._start_analysis_build.assert_called_once_with()


def test_choose_new_home_previews_plc_named_paths(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "workspaces"
    home.mkdir()
    monkeypatch.setattr(
        "clicknick.workspace_controller.filedialog.askdirectory", MagicMock(return_value=str(home))
    )

    app = _app(ConnectionSession(ClickConnection("1", 2, "LaserBall.ckp")))
    app._workspace._ensure_plc_name = MagicMock(return_value="LaserBall")

    app._workspace._select_location()

    assert app._session.pending_workspace == _config(home, "LaserBall")
    app.mirror_project_selection_var.set.assert_called_once_with("")
    app.mirror_location_selection_var.set.assert_called_once_with(str(home / "LaserBall Workspace"))
    app.workspace_setup_action_var.set.assert_called_once_with("Create Workspace")


def test_find_existing_workspace_selects_a_folder_not_a_config_file(
    monkeypatch, tmp_path: Path
) -> None:
    config = _config(tmp_path, "LaserBall")
    save_project_workspace_config(config)
    monkeypatch.setattr(
        "clicknick.workspace_controller.filedialog.askdirectory",
        MagicMock(return_value=str(config.workspace_path)),
    )

    app = _app(ConnectionSession(ClickConnection("1", 2, "LaserBall.ckp")))
    app._workspace._ensure_plc_name = MagicMock(return_value="LaserBall")

    app._workspace._select_existing()

    assert app._session.pending_workspace == config
    app.mirror_project_selection_var.set.assert_called_once_with(str(config.workspace_path))
    app.mirror_location_selection_var.set.assert_called_once_with("")
    app.workspace_setup_action_var.set.assert_called_once_with("Use Workspace")


def test_workspace_setup_prompts_for_and_writes_a_missing_plc_name(monkeypatch) -> None:
    ask_name = MagicMock(side_effect=["Bad.Name", "  Line 1  "])
    write_name = MagicMock()
    monkeypatch.setattr("clicknick.workspace_controller.simpledialog.askstring", ask_name)
    monkeypatch.setattr("clicknick.workspace_controller.messagebox.showerror", MagicMock())
    monkeypatch.setattr("clicknick.workspace_controller.messagebox.showinfo", MagicMock())
    monkeypatch.setattr("pyclickplc.project.write_plc_name", write_name)
    monkeypatch.setattr(
        "clicknick.utils.click_temp.click_temp_dir", MagicMock(return_value=Path("CLICK-temp"))
    )

    app = _app(ConnectionSession(ClickConnection("1", 123, "Example.ckp"), has_database=True))
    app._workspace.plc_name = MagicMock(return_value=None)

    assert app._workspace._ensure_plc_name() == "Line 1"
    assert ask_name.call_count == 2
    write_name.assert_called_once_with(Path("CLICK-temp") / "Project.ini", "Line 1")
    app.plc_name_var.set.assert_called_once_with("Line 1")


def test_a_folder_chosen_after_the_click_window_showed_another_project_is_dropped(
    monkeypatch, tmp_path: Path
) -> None:
    home = tmp_path / "workspaces"
    home.mkdir()
    first = ConnectionSession(ClickConnection("1", 2, "LaserBall.ckp"))
    first.setup_window = MagicMock()
    other = ConnectionSession(ClickConnection("1", 2, "Other.ckp"))
    app = _app(first)
    app._workspace._ensure_plc_name = MagicMock(return_value="LaserBall")

    def choose_after_project_change(**_options):
        first.close()  # CLICK opened another project while the dialog was up
        app._session = other
        return str(home)

    monkeypatch.setattr(
        "clicknick.workspace_controller.filedialog.askdirectory", choose_after_project_change
    )

    app._workspace._select_location()

    assert other.pending_workspace is None
    assert other.pairing.matches == []
    app.mirror_location_selection_var.set.assert_not_called()


def test_a_plc_name_entered_after_the_click_window_closed_is_not_written(monkeypatch) -> None:
    write_name = MagicMock()
    monkeypatch.setattr("pyclickplc.project.write_plc_name", write_name)
    session = ConnectionSession(ClickConnection("1", 123, "Example.ckp"), has_database=True)
    app = _app(session)
    app._workspace.plc_name = MagicMock(return_value=None)

    def answer_after_close(*_args, **_options):
        session.close()  # CLICK's window closed while the prompt was up
        app._session = None
        return "Line 1"

    monkeypatch.setattr("clicknick.workspace_controller.simpledialog.askstring", answer_after_close)

    assert app._workspace._ensure_plc_name() is None
    write_name.assert_not_called()


def test_setup_confirmed_after_the_click_window_closed_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    config = _config(tmp_path / "Desktop", "IMHERE")
    config.workspace_path.mkdir(parents=True)
    (config.workspace_path / "notes.txt").write_text("kept\n", encoding="utf-8")
    save_config = MagicMock(return_value=config.sidecar_path)
    remember = MagicMock()
    monkeypatch.setattr(
        "clicknick.services.workspace_mirror.save_project_workspace_config", save_config
    )
    monkeypatch.setattr("clicknick.services.workspace_mirror.remember_project_sidecar", remember)
    session = ConnectionSession(ClickConnection("1", 2, "IMHERE.ckp"), has_database=True)
    session.setup_window = MagicMock()
    session.pending_workspace = config
    session.use_workspace = MagicMock()
    app = _app(session)
    app._workspace._ensure_plc_name = MagicMock(return_value="IMHERE")
    app._workspace.source_dir = MagicMock(return_value=None)

    def confirm_after_close(*_args, **_options):
        session.close()  # CLICK's window closed while the question was up
        app._session = None
        return True

    monkeypatch.setattr(
        "clicknick.workspace_controller.messagebox.askokcancel", confirm_after_close
    )

    app._workspace._apply_setup()

    save_config.assert_not_called()
    remember.assert_not_called()
    session.use_workspace.assert_not_called()
    app._start_analysis_build.assert_not_called()


def test_open_workspace_uses_single_active_folder(tmp_path: Path) -> None:
    workspace = tmp_path / "LaserBall Workspace"
    controller = _app(None)._workspace
    controller.display_dir = MagicMock(return_value=workspace)
    controller._open_folder = MagicMock()

    controller.open_workspace()

    controller._open_folder.assert_called_once_with(
        workspace,
        title="Open Workspace",
        unavailable="Workspace is not available",
    )
