"""Selection, transport failures, and real Jet operations on disposable MDBs."""

from __future__ import annotations

import io
import json
import queue
import shutil
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pyodbc
import pytest

from clicknick.utils import jet_sidecar, mdb_operations, mdb_shared


@pytest.fixture(autouse=True)
def automatic_backend(monkeypatch):
    monkeypatch.setenv("CLICKNICK_DB_BACKEND", "auto")


def test_native_odbc_prevents_starting_jet(tmp_path, monkeypatch):
    path = tmp_path / "database.mdb"
    path.touch()
    driver = "Microsoft Access Driver (*.mdb, *.accdb)"
    monkeypatch.setattr(mdb_shared, "get_available_access_drivers", lambda: [driver])
    native = Mock()
    monkeypatch.setattr(mdb_shared.pyodbc, "connect", lambda _text: native)
    jet = Mock(side_effect=AssertionError("Jet must not start"))
    monkeypatch.setattr(mdb_shared, "JetConnection", jet)
    assert mdb_shared.create_access_connection(path) is native
    jet.assert_not_called()


@pytest.mark.parametrize("drivers", [[], ["Microsoft Access Driver (*.mdb, *.accdb)"]])
def test_missing_or_unloadable_driver_falls_back(tmp_path, monkeypatch, drivers):
    path = tmp_path / "database.mdb"
    path.touch()
    monkeypatch.setattr(mdb_shared, "get_available_access_drivers", lambda: drivers)
    monkeypatch.setattr(
        mdb_shared.pyodbc, "connect", Mock(side_effect=pyodbc.Error("IM003", "load failed"))
    )
    jet = Mock()
    monkeypatch.setattr(mdb_shared, "JetConnection", jet)
    assert mdb_shared.create_access_connection(path) is jet.return_value
    jet.assert_called_once_with(path)


def test_database_error_does_not_switch_backends(tmp_path, monkeypatch):
    path = tmp_path / "database.mdb"
    path.touch()
    monkeypatch.setattr(
        mdb_shared, "get_available_access_drivers", lambda: ["Microsoft Access Driver (*.mdb)"]
    )
    monkeypatch.setattr(
        mdb_shared.pyodbc, "connect", Mock(side_effect=pyodbc.Error("HY000", "locked"))
    )
    jet = Mock()
    monkeypatch.setattr(mdb_shared, "JetConnection", jet)
    with pytest.raises(RuntimeError, match="locked"):
        mdb_shared.create_access_connection(path)
    jet.assert_not_called()


def test_candidate_check_does_not_launch_process(monkeypatch):
    monkeypatch.setattr(mdb_shared, "has_access_driver", lambda: False)
    monkeypatch.setattr(mdb_shared, "jet_is_available", lambda: True)
    assert mdb_shared.has_database_backend()


def test_connection_test_handles_missing_project():
    result = mdb_shared.probe_database_connection(None)
    assert not result.success
    assert "Open a CLICK project" in result.message


def test_connection_test_reads_and_closes_native_connection(tmp_path, monkeypatch):
    native = Mock()
    monkeypatch.setattr(mdb_shared, "create_access_connection", lambda _path: native)
    result = mdb_shared.probe_database_connection(tmp_path / "database.mdb")
    assert result.success and "ODBC" in result.message
    sql = native.cursor.return_value.execute.call_args.args[0]
    assert sql.startswith("SELECT TOP 1") and "[Retentive]" in sql
    native.commit.assert_not_called()
    native.close.assert_called_once()


def test_connection_test_returns_read_error_and_closes(monkeypatch):
    native = Mock()
    native.cursor.return_value.execute.side_effect = RuntimeError("missing address table")
    monkeypatch.setattr(mdb_shared, "create_access_connection", lambda _path: native)
    result = mdb_shared.probe_database_connection("database.mdb")
    assert not result.success and "missing address table" in result.message
    native.close.assert_called_once()


def test_save_timeout_is_not_replayed(monkeypatch):
    worker = jet_sidecar.JetWorker()
    process = Mock()
    process.stdin = io.BytesIO()
    worker._process = process
    stop = Mock()
    monkeypatch.setattr(worker, "_stop", stop)
    monkeypatch.setattr(jet_sidecar, "SAVE_TIMEOUT", 0.01)
    with pytest.raises(jet_sidecar.JetTransportError, match="outcome is unknown"):
        worker._exchange("save", path="database.mdb", deletes=[], upserts=[])
    assert process.stdin.getvalue().count(b"\n") == 1
    stop.assert_called_once()


def test_rejects_oversized_save_before_sending(monkeypatch):
    worker = jet_sidecar.JetWorker()
    worker._process = Mock()
    monkeypatch.setattr(jet_sidecar, "MAX_REQUEST_BYTES", 100)
    with pytest.raises(jet_sidecar.JetError, match="too large"):
        worker._exchange("save", upserts=["x" * 200])
    worker._process.stdin.write.assert_not_called()


def test_reported_database_failure_does_not_restart_worker(monkeypatch):
    worker = jet_sidecar.JetWorker()
    worker._process = Mock()
    worker._responses = queue.Queue()
    worker._responses.put(json.dumps({"id": 1, "ok": False, "error": "currently locked"}).encode())
    stop = Mock()
    monkeypatch.setattr(worker, "_stop", stop)
    with pytest.raises(jet_sidecar.JetError, match="currently locked"):
        worker._exchange("save", deletes=[], upserts=[])
    stop.assert_not_called()


@pytest.fixture
def jet_database(tmp_path, monkeypatch):
    if not jet_sidecar.is_available():
        pytest.skip("Windows x86 PowerShell is not available")
    path = tmp_path / "SC_.mdb"
    shutil.copy2(Path(__file__).with_name("SC_.mdb"), path)
    worker = jet_sidecar.JetWorker()
    monkeypatch.setattr(jet_sidecar, "_worker", worker)
    monkeypatch.setattr(mdb_shared, "get_available_access_drivers", lambda: [])
    try:
        # A missing provider/policy is a meaningful test failure on an x86-capable Windows host.
        yield path, worker
    finally:
        worker.close()


def test_real_jet_fallback_load_save_and_readonly_connection_test(jet_database):
    path, worker = jet_database
    before = path.read_bytes()
    result = mdb_shared.probe_database_connection(path)
    assert result.success and jet_sidecar.BACKEND_NAME in result.message
    assert path.read_bytes() == before
    process = worker._process
    with mdb_operations.MdbConnection(str(path)) as connection:
        original = mdb_operations.load_all_addresses(connection)
        row = next(iter(original.values()))
        changed = replace(
            row,
            nickname="JET_TEST",
            comment="O'Brien\r\n" + "note " * 500,
            initial_value="0000123",
            retentive=not row.retentive,
        )
        assert mdb_operations.save_changes(connection, [changed]) == 1
    with mdb_operations.MdbConnection(str(path)) as connection:
        actual = mdb_operations.load_all_addresses(connection)[row.addr_key]
        assert (actual.nickname, actual.comment, actual.initial_value, actual.retentive) == (
            changed.nickname,
            changed.comment,
            changed.initial_value,
            changed.retentive,
        )
        mdb_operations.save_changes(connection, [row])
    assert worker._process is process
    result = mdb_operations.ensure_addresses_exist(str(path), ["C1999"])
    assert result["inserted_count"] == 1
    with mdb_operations.MdbConnection(str(path)) as connection:
        added = [
            r for k, r in mdb_operations.load_all_addresses(connection).items() if k not in original
        ]
        mdb_operations.save_changes(connection, [replace(r, used=False) for r in added])
        assert mdb_operations.load_all_addresses(connection) == original


def test_real_jet_failed_batch_rolls_back(jet_database):
    path, worker = jet_database
    baseline = worker.request("read", path=str(path))["rows"]
    row = baseline[0]
    update = [row[0], row[1], row[2], row[6], "ROLLBACK_TEST", row[4], row[7], row[8]]
    # A NULL primary key after the first update must roll back the entire batch.
    invalid = [None, "C", "999", 0, "INVALID", "", "", False]
    with pytest.raises(jet_sidecar.JetError):
        worker.request("save", path=str(path), deletes=[], upserts=[update, invalid])
    assert worker.request("read", path=str(path))["rows"] == baseline


def test_connection_test_reports_close_errors(monkeypatch):
    native = Mock()
    native.close.side_effect = RuntimeError("close failed")
    monkeypatch.setattr(mdb_shared, "create_access_connection", lambda _path: native)
    result = mdb_shared.probe_database_connection("database.mdb")
    assert not result.success and "close failed" in result.message


@pytest.mark.parametrize("drivers", [[], ["Microsoft Access Driver (*.mdb)"]])
def test_forced_odbc_never_starts_jet(tmp_path, monkeypatch, drivers):
    path = tmp_path / "database.mdb"
    path.touch()
    monkeypatch.setenv("CLICKNICK_DB_BACKEND", "odbc")
    monkeypatch.setattr(mdb_shared, "get_available_access_drivers", lambda: drivers)
    monkeypatch.setattr(
        mdb_shared.pyodbc, "connect", Mock(side_effect=pyodbc.Error("IM003", "load failed"))
    )
    jet = Mock()
    monkeypatch.setattr(mdb_shared, "JetConnection", jet)
    with pytest.raises(RuntimeError):
        mdb_shared.create_access_connection(path)
    jet.assert_not_called()
    assert not mdb_shared.uses_jet_backend()


def test_forced_jet_ignores_available_odbc_and_tests_real_connection(jet_database, monkeypatch):
    path, _worker = jet_database
    monkeypatch.setenv("CLICKNICK_DB_BACKEND", "jet")
    monkeypatch.setattr(
        mdb_shared,
        "get_available_access_drivers",
        lambda: ["Microsoft Access Driver (*.mdb, *.accdb)"],
    )
    native = Mock(side_effect=AssertionError("Native ODBC must not be used"))
    monkeypatch.setattr(mdb_shared.pyodbc, "connect", native)
    assert mdb_shared.uses_jet_backend()
    result = mdb_shared.probe_database_connection(path)
    assert result.success and jet_sidecar.BACKEND_NAME in result.message
    native.assert_not_called()


@pytest.mark.parametrize("backend", ["auto", "odbc", "jet", "none"])
def test_cli_backend_override_precedes_environment_and_gui_start(monkeypatch, backend):
    import os

    from clicknick import app as app_module

    monkeypatch.setenv("CLICKNICK_DB_BACKEND", "odbc")
    requested = []
    instance = Mock()

    def create_app():
        requested.append(os.environ["CLICKNICK_DB_BACKEND"])
        return instance

    monkeypatch.setattr(app_module, "ClickNickApp", create_app)
    app_module.main(["--db-backend", backend])
    assert requested == [backend]
    assert mdb_shared.get_database_backend() == backend
    instance.run.assert_called_once()


def test_cli_honors_environment_without_override(monkeypatch):
    from clicknick import app as app_module

    monkeypatch.setenv("CLICKNICK_DB_BACKEND", "jet")
    monkeypatch.setattr(app_module, "ClickNickApp", Mock())
    app_module.main([])
    assert mdb_shared.get_database_backend() == "jet"


def test_cli_rejects_invalid_backend_before_gui_start(monkeypatch):
    from clicknick import app as app_module

    factory = Mock()
    monkeypatch.setattr(app_module, "ClickNickApp", factory)
    with pytest.raises(SystemExit) as exc:
        app_module.main(["--db-backend", "unknown"])
    assert exc.value.code == 2
    factory.assert_not_called()


def test_cli_rejects_invalid_environment_before_gui_start(monkeypatch):
    from clicknick import app as app_module

    monkeypatch.setenv("CLICKNICK_DB_BACKEND", "unknown")
    factory = Mock()
    monkeypatch.setattr(app_module, "ClickNickApp", factory)
    with pytest.raises(SystemExit) as exc:
        app_module.main([])
    assert exc.value.code == 2
    factory.assert_not_called()


@pytest.mark.parametrize("path", [None, "missing.mdb"])
def test_none_disables_database_connections_and_probes(monkeypatch, path):
    monkeypatch.setenv("CLICKNICK_DB_BACKEND", "none")
    native = Mock(side_effect=AssertionError("ODBC must not be used"))
    jet = Mock(side_effect=AssertionError("Jet must not be used"))
    monkeypatch.setattr(mdb_shared, "get_available_access_drivers", native)
    monkeypatch.setattr(mdb_shared.pyodbc, "connect", native)
    monkeypatch.setattr(mdb_shared, "jet_is_available", jet)
    monkeypatch.setattr(mdb_shared, "JetConnection", jet)
    assert not mdb_shared.has_database_backend()
    assert not mdb_shared.uses_jet_backend()
    result = mdb_shared.probe_database_connection(path)
    assert not result.success and "CSV mode" in result.message
    with pytest.raises(RuntimeError, match="CSV mode"):
        mdb_shared.create_access_connection(path)
    native.assert_not_called()
    jet.assert_not_called()


def test_none_connects_through_existing_csv_flow(monkeypatch):
    from types import SimpleNamespace

    from clicknick import app as app_module

    monkeypatch.setenv("CLICKNICK_DB_BACKEND", "none")
    view = SimpleNamespace(
        root=Mock(),
        _session=None,
        _csv_only_store=None,
        _csv_only_dataview=None,
        monitoring=False,
        _clear_connection_state=Mock(),
        csv_path_var=Mock(),
        _load_workspace_pairing=Mock(),
        nickname_manager=SimpleNamespace(has_database_backend=mdb_shared.has_database_backend),
        _show_main_window=Mock(),
        load_csv=Mock(),
    )
    view._connect_csv_fallback = lambda *args: app_module.ClickNickApp._connect_csv_fallback(
        view, *args
    )
    monkeypatch.setattr(app_module, "find_fallback_csv", lambda _hwnd: "Address.csv")
    dialog = Mock()
    dialog.return_value.show.return_value = "saved.csv"
    monkeypatch.setattr(app_module, "CsvFallbackDialog", dialog)
    probe = Mock(side_effect=AssertionError("Database probe must not run"))
    monkeypatch.setattr(mdb_shared, "probe_database_connection", probe)
    app_module.ClickNickApp.connect_to_instance(view, 1, "CLICK", "project.ckp", 2)
    dialog.assert_called_once_with(view.root, "Address.csv", "project_Address.csv")
    view.csv_path_var.set.assert_called_with("saved.csv")
    view.load_csv.assert_called_once()
    assert view._session is None
    probe.assert_not_called()


@pytest.mark.parametrize("op,expected_timeout", [("save", 180.0), ("probe", 30.0)])
def test_operation_deadline_keeps_startup_short(monkeypatch, op, expected_timeout):
    worker = jet_sidecar.JetWorker()
    worker._process = Mock()
    worker._responses = Mock()
    worker._responses.get.return_value = b'{"id":1,"ok":true,"result":{}}'
    worker._exchange(op)
    worker._responses.get.assert_called_once_with(timeout=expected_timeout)


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_unloadable_odbc_loads_off_ui_thread_and_handles_result(jet_database, monkeypatch, outcome):
    import threading
    from types import SimpleNamespace

    from clicknick import app as app_module
    from clicknick import connection_session
    from clicknick.data import data_source

    path, _worker = jet_database
    callbacks = []
    ui_thread = threading.get_ident()
    native_threads = []
    view = SimpleNamespace(
        root=SimpleNamespace(after=lambda _delay, callback: callbacks.append(callback)),
        _session=None,
        _update_status=Mock(),
        _show_main_window=Mock(),
        _connect_csv_fallback=Mock(),
        _configured_workspace_dir=lambda: None,
        _on_sync_status_changed=Mock(),
        nickname_manager=Mock(),
        load_from_database=Mock(),
        _start_analysis_build=Mock(),
    )
    monkeypatch.setattr(data_source, "find_click_database", lambda *_args: str(path))
    monkeypatch.setattr(
        mdb_shared, "get_available_access_drivers", lambda: ["Microsoft Access Driver (*.mdb)"]
    )

    def native_connect(_text):
        native_threads.append(threading.get_ident())
        raise pyodbc.Error("IM003", "load failed")

    monkeypatch.setattr(mdb_shared.pyodbc, "connect", native_connect)
    if outcome == "failure":
        monkeypatch.setattr(
            mdb_shared, "JetConnection", Mock(side_effect=RuntimeError("policy blocked"))
        )
    threads = []
    thread_factory = threading.Thread

    def create_thread(*args, **kwargs):
        thread = thread_factory(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(threading, "Thread", create_thread)
    monitoring = Mock()
    monkeypatch.setattr(app_module.AddressStore, "start_file_monitoring", monitoring)
    session = Mock()
    monkeypatch.setattr(connection_session, "ConnectionSession", session)
    error = Mock()
    monkeypatch.setattr(app_module.messagebox, "showerror", error)

    app_module.ClickNickApp._load_instance_database(view, 1, "project.ckp", 2)
    assert view._session is None
    threads[0].join(timeout=30)
    assert not threads[0].is_alive(), "Background database load did not finish"
    assert native_threads and all(t != ui_thread for t in native_threads)
    if outcome == "cancelled":
        view._connection_probe_token = None
    callbacks.pop(0)()
    if outcome == "success":
        store = session.call_args.args[3]
        assert store.loaded_row_count == 408
        assert view._session is session.return_value
        view.nickname_manager.set_shared_data.assert_called_once_with(store)
        monitoring.assert_called_once_with(view.root)
        view._connect_csv_fallback.assert_not_called()
        error.assert_not_called()
    elif outcome == "failure":
        session.assert_not_called()
        error.assert_called_once()
        assert "policy blocked" in error.call_args.args[1]
        view._connect_csv_fallback.assert_called_once_with("project.ckp", 2)
    else:
        session.assert_not_called()
        monitoring.assert_not_called()
        view._connect_csv_fallback.assert_not_called()
        error.assert_not_called()


def test_switch_closes_old_session_before_loading_new_database(monkeypatch):
    from types import SimpleNamespace

    from clicknick import app as app_module

    events = []
    previous = Mock()
    previous.close.side_effect = lambda **_kwargs: events.append("close") or True
    view = SimpleNamespace(
        _session=previous,
        _csv_only_store=None,
        _csv_only_dataview=None,
        monitoring=False,
        nickname_manager=Mock(),
        _clear_connection_state=Mock(),
        csv_path_var=Mock(),
        _load_workspace_pairing=Mock(),
        _load_instance_database=lambda *_args: events.append("load"),
    )
    app_module.ClickNickApp.connect_to_instance(view, 1, "CLICK", "project.ckp", 2)
    assert events == ["close", "load"]
    assert view._session is None


def test_real_jet_full_sheet_insert_update_rollback_delete(jet_database):
    from clicknick.data.address_store import AddressStore
    from clicknick.data.data_source import MdbDataSource

    path, worker = jet_database
    store = AddressStore(MdbDataSource(db_path=str(path)))
    skeleton = store._create_base_skeleton()
    assert len(skeleton) == 13340
    rows = [
        replace(row, nickname=f"BENCH_{row.memory_type}_{row.address}", comment="C" * 128)
        for row in skeleton.values()
    ]
    with mdb_operations.MdbConnection(str(path)) as connection:
        assert mdb_operations.save_changes(connection, rows) == len(rows)
        loaded = mdb_operations.load_all_addresses(connection)
        assert len(loaded) == len(rows)
        assert all(loaded[row.addr_key].comment == row.comment for row in rows)
        updated = [replace(row, comment="U" * 128) for row in rows]
        assert mdb_operations.save_changes(connection, updated) == len(rows)
        baseline = mdb_operations.load_all_addresses(connection)
        assert all(baseline[row.addr_key].comment == row.comment for row in updated)

        # Fail only after every valid update, proving a large transaction rolls back.
        upserts = [
            [
                row.addr_key,
                row.memory_type,
                str(row.address),
                int(row.data_type),
                row.nickname,
                "ROLLBACK",
                row.initial_value,
                row.retentive,
            ]
            for row in rows
        ]
        upserts.append([None, "C", "999", 0, "INVALID", "", "", False])
        with pytest.raises(jet_sidecar.JetError):
            worker.request("save", path=str(path), deletes=[], upserts=upserts)
        assert mdb_operations.load_all_addresses(connection) == baseline
        worker.request("save", path=str(path), deletes=list(skeleton), upserts=[])
        assert mdb_operations.load_all_addresses(connection) == {}


def test_real_jet_reused_commands_preserve_nulls_and_variable_text(jet_database):
    path, worker = jet_database
    original = worker.request("read", path=str(path))["rows"][:3]
    comments = ["", "O'Brien\r\n" + "text " * 1900, None]
    initials = ["0000123", None, "0"]
    upserts = [
        [row[0], row[1], row[2], row[6], f"REUSE_{i}", comments[i], initials[i], i % 2 == 0]
        for i, row in enumerate(original)
    ]
    worker.request("save", path=str(path), deletes=[], upserts=upserts)
    loaded = {row[0]: row for row in worker.request("read", path=str(path))["rows"]}
    for i, row in enumerate(original):
        actual = loaded[row[0]]
        assert (actual[3], actual[4], actual[7], actual[8]) == (
            f"REUSE_{i}",
            comments[i],
            initials[i],
            i % 2 == 0,
        )
