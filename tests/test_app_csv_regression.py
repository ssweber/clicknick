"""Regression tests for app state transitions around CSV-only loading."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from clicknick.app import ClickNickApp


class FakeVar:
    """Minimal Tk-like variable for get/set in unit tests."""

    def __init__(self, value: str = ""):
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class FakeCsvDataSource:
    """Minimal CSV data source stand-in for app.load_csv tests."""

    def __init__(self, csv_path: str):
        self.csv_path = csv_path


class FakeAddressStore:
    """Minimal AddressStore stand-in for app.load_csv tests."""

    def __init__(self, data_source):
        self.data_source = data_source
        self.load_initial_data = MagicMock()
        self.start_file_monitoring = MagicMock()


def _make_app_stub() -> ClickNickApp:
    app = ClickNickApp.__new__(ClickNickApp)
    app._shared_address_data = None
    app._shared_data_source_path = None
    app._update_status = MagicMock()
    app._update_window_title = MagicMock()
    app.start_monitoring = MagicMock()
    app.stop_monitoring = MagicMock()
    app.root = MagicMock()
    app.monitoring = False
    app.using_database = True
    return app


def test_load_csv_with_stale_connection_skips_monitoring_and_clears_connection(monkeypatch):
    monkeypatch.setattr("clicknick.data.data_source.CsvDataSource", FakeCsvDataSource)
    monkeypatch.setattr("clicknick.app.AddressStore", FakeAddressStore)

    app = _make_app_stub()
    app.csv_path_var = FakeVar("C:/tmp/NicknameExport.csv")
    app.selected_instance_var = FakeVar("OldProject.ckp")
    app.connected_click_pid = 1234
    app.connected_click_hwnd = 5678
    app.connected_click_filename = "OldProject.ckp"
    app.detector = SimpleNamespace(check_window_exists=lambda _pid: False)
    app.settings = SimpleNamespace(sort_by_nickname=False)
    app.nickname_manager = SimpleNamespace(
        set_shared_data=MagicMock(),
        apply_sorting=MagicMock(),
    )

    result = app.load_csv()

    assert result is True
    assert app.start_monitoring.call_count == 0
    assert app.connected_click_pid is None
    assert app.connected_click_hwnd is None
    assert app.connected_click_filename is None
    assert app.selected_instance_var.get() == ""
    assert app._shared_data_source_path == "C:/tmp/NicknameExport.csv"
    app.nickname_manager.set_shared_data.assert_called_once_with(app._shared_address_data)


def test_handle_window_closed_preserves_csv_loaded_store():
    app = _make_app_stub()
    csv_path = "C:/tmp/NicknameExport.csv"
    store = SimpleNamespace(force_close_all_windows=MagicMock())

    app._shared_data_source_path = csv_path
    app._shared_address_data = store
    app.nickname_manager = SimpleNamespace(set_shared_data=MagicMock())
    app.selected_instance_var = FakeVar("MyProject.ckp")
    app.connected_click_pid = 111
    app.connected_click_hwnd = 222
    app.connected_click_filename = "MyProject.ckp"
    app.refresh_click_instances = MagicMock()
    app.root = SimpleNamespace(after=MagicMock())

    app._handle_window_closed()

    app.stop_monitoring.assert_called_once_with(update_status=False)
    assert app._shared_data_source_path == csv_path
    assert app._shared_address_data is store
    app.nickname_manager.set_shared_data.assert_not_called()
    store.force_close_all_windows.assert_not_called()
    assert app.connected_click_pid is None
    assert app.connected_click_hwnd is None
    assert app.connected_click_filename is None
    assert app.selected_instance_var.get() == ""
    app.root.after.assert_called_once_with(2000, app.refresh_click_instances)
