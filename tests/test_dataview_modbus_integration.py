"""Dataview Modbus integration tests (panel + window behavior)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from pyclickplc.addresses import normalize_address
from pyclickplc.dataview import DataviewFile, DataviewRow

from clicknick.views.dataview_editor.panel import (
    COL_NEW_VALUE,
    DataviewPanel,
)
from clicknick.views.dataview_editor.window import ConnectionState, DataviewEditorWindow


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeWidget:
    def __init__(self):
        self.last_config: dict[str, object] = {}

    def config(self, **kwargs):
        self.last_config.update(kwargs)


class FakeMenu:
    def __init__(self, *args, **kwargs):
        self.commands: dict[str, object] = {}
        self.entry_states: dict[str, str] = {}

    def add_cascade(self, label, menu):
        self.commands[label] = menu

    def add_command(self, label, command=None, **kwargs):
        self.commands[label] = command

    def add_separator(self):
        return None

    def add_checkbutton(self, **kwargs):
        return None

    def entryconfig(self, label, state):
        self.entry_states[label] = state


class FakeSheet:
    def __init__(self):
        self.cells: dict[tuple[int, int], object] = {}

    def get_cell_data(self, row, col):
        return self.cells.get((row, col), "")

    def set_cell_data(self, row, col, value):
        self.cells[(row, col)] = value

    def create_checkbox(self, r, c, checked=False, text=""):
        self.cells[(r, c)] = bool(checked)

    def delete_checkbox(self, row, col):
        return None


class FakePanel:
    def __init__(
        self,
        name: str,
        poll_addresses: list[str] | None = None,
        write_rows: list[tuple[str, object]] | None = None,
        write_all_rows: list[tuple[str, object]] | None = None,
    ):
        self.name = name
        self.file_path = Path(f"{name}.cdv")
        self.is_dirty = False
        self._poll_addresses = poll_addresses or []
        self._write_rows = write_rows or []
        self._write_all_rows = write_all_rows or []
        self.live_cleared = 0
        self.write_checks_cleared = 0
        self.last_live_values = None
        self.destroyed = False

    def get_poll_addresses(self):
        return list(self._poll_addresses)

    def clear_live_values(self):
        self.live_cleared += 1

    def update_live_values(self, values):
        self.last_live_values = dict(values)

    def get_write_rows(self):
        return list(self._write_rows)

    def get_write_all_rows(self):
        return list(self._write_all_rows)

    def clear_write_checks(self):
        self.write_checks_cleared += 1

    def destroy(self):
        self.destroyed = True


class FakeNotebook:
    def __init__(self, panels: list[FakePanel]):
        self._ids = [f"tab{i}" for i in range(len(panels))]
        self._panel_map = dict(zip(self._ids, panels, strict=False))
        self._selected = self._ids[0] if self._ids else ""

    def tabs(self):
        return list(self._ids)

    def nametowidget(self, tab_id):
        return self._panel_map[tab_id]

    def select(self, value=None):
        if value is None:
            return self._selected
        self._selected = value
        return self._selected

    def index(self, arg):
        if arg == "end":
            return len(self._ids)
        if arg in self._ids:
            return self._ids.index(arg)
        for i, tab_id in enumerate(self._ids):
            if self._panel_map[tab_id] is arg:
                return i
        raise IndexError(arg)

    def set_current_index(self, idx: int):
        self._selected = self._ids[idx]


class FakeModbusService:
    def __init__(self):
        self.connect_calls: list[tuple[str, int]] = []
        self.set_poll_calls: list[list[str]] = []
        self.clear_poll_calls = 0
        self.disconnect_calls = 0
        self.write_calls: list[list[tuple[str, object]]] = []
        self.write_result = [{"address": "X001", "ok": True, "error": None}]

    def connect(self, host, port):
        self.connect_calls.append((host, port))

    def set_poll_addresses(self, addresses):
        self.set_poll_calls.append(list(addresses))

    def clear_poll_addresses(self):
        self.clear_poll_calls += 1

    def disconnect(self):
        self.disconnect_calls += 1

    def write(self, values):
        self.write_calls.append(list(values))
        return list(self.write_result)


def _make_panel_stub(rows: list[DataviewRow]) -> DataviewPanel:
    panel = DataviewPanel.__new__(DataviewPanel)
    panel.rows = rows
    panel.address_normalizer = normalize_address
    panel.nickname_lookup = None
    panel.on_modified = None
    panel.on_addresses_changed = None
    panel._write_checks = [False] * len(rows)
    panel._live_values = {}
    panel._suppress_notifications = False
    panel._is_dirty = False
    panel.sheet = FakeSheet()
    panel._update_status = lambda: None
    return panel


def _make_window_stub(
    panels: list[FakePanel],
    *,
    connected: bool,
) -> DataviewEditorWindow:
    window = DataviewEditorWindow.__new__(DataviewEditorWindow)
    window.notebook = FakeNotebook(panels)
    window._open_panels = {panel.file_path: panel for panel in panels}
    window._active_panel = panels[0] if panels else None
    window._pending_closed_panel = None
    window._modbus = FakeModbusService()
    window._modbus_busy = False
    window._modbus_write_busy = False
    window._connection_state = (
        ConnectionState.CONNECTED if connected else ConnectionState.DISCONNECTED
    )
    window._modbus_host_var = FakeVar("127.0.0.1")
    window._modbus_port_var = FakeVar("502")
    window._modbus_toggle_var = FakeVar("Connect")
    window._set_modbus_error_text = lambda text="": None
    window.write_checked_button = FakeWidget()
    window.write_all_button = FakeWidget()
    window.modbus_connect_button = FakeWidget()
    window.host_entry = FakeWidget()
    window.port_entry = FakeWidget()
    window.connection_menu = FakeMenu()
    window._iter_open_panels = lambda: list(panels)
    window.after = MagicMock(side_effect=lambda _delay, callback: callback())
    window._run_background = lambda target, *args: target(*args)
    return window


def _row(address: str, value=None) -> DataviewRow:
    row = DataviewRow(address=address, new_value=value)
    row.update_data_type()
    return row


def test_panel_get_poll_addresses_canonical_dedup_valid_only():
    panel = _make_panel_stub([_row("x1"), _row("X001"), _row(""), _row("bad"), _row("ds1")])
    assert panel.get_poll_addresses() == ["X001", "DS1"]


def test_panel_write_row_filters_writability_checks_and_nonempty_new_value():
    panel = _make_panel_stub([_row("X001", True), _row("ds1", 12), _row("XD0", 5)])
    panel._write_checks = [True, False, True]

    assert panel.get_write_rows() == [("X001", True)]
    assert panel.get_write_all_rows() == [("X001", True), ("DS1", 12)]


def test_panel_new_value_validation_uses_dataview_helpers(monkeypatch):
    panel = _make_panel_stub([_row("DS1", 1)])

    calls = {"validate": 0, "parse": 0}

    def _validate(row, display):
        calls["validate"] += 1
        return True, ""

    def _parse(display, data_type):
        calls["parse"] += 1
        return SimpleNamespace(ok=True, value=42, error="")

    monkeypatch.setattr(DataviewFile, "validate_row_display", staticmethod(_validate))
    monkeypatch.setattr(DataviewFile, "try_parse_display", staticmethod(_parse))
    monkeypatch.setattr(
        DataviewFile, "value_to_display", staticmethod(lambda value, data_type: "42")
    )

    event = SimpleNamespace(row=0, column=COL_NEW_VALUE, value=" 42 ")
    assert panel._validate_edit(event) == "42"
    assert calls == {"validate": 1, "parse": 1}


def test_panel_sheet_modified_updates_new_value_from_display_helper(monkeypatch):
    panel = _make_panel_stub([_row("DS1", None)])
    panel.sheet.set_cell_data(0, COL_NEW_VALUE, "7")
    called = {"set": 0}

    def _setter(row, display):
        called["set"] += 1
        row.new_value = int(display)

    monkeypatch.setattr(DataviewFile, "set_row_new_value_from_display", staticmethod(_setter))
    event = SimpleNamespace(cells={"table": {(0, COL_NEW_VALUE): ""}})

    panel._on_sheet_modified(event)

    assert called["set"] == 1
    assert panel.rows[0].new_value == 7


def test_toolbar_toggle_routes_to_connect_disconnect_handlers():
    window = _make_window_stub([], connected=False)
    window._connect_modbus = MagicMock()
    window._disconnect_modbus = MagicMock()

    window._toggle_modbus_connection()
    window._connect_modbus.assert_called_once()

    window._connection_state = ConnectionState.CONNECTED
    window._toggle_modbus_connection()
    window._disconnect_modbus.assert_called_once()


def test_connection_menu_uses_same_handlers(monkeypatch):
    monkeypatch.setattr("clicknick.views.dataview_editor.window.tk.Menu", FakeMenu)
    monkeypatch.setattr("clicknick.views.dataview_editor.window.tk.BooleanVar", FakeVar)

    window = DataviewEditorWindow.__new__(DataviewEditorWindow)
    window.config = lambda **kwargs: None
    window.bind = lambda *args, **kwargs: None
    window._new_dataview = MagicMock()
    window._open_file = MagicMock()
    window._save_current = MagicMock()
    window._export = MagicMock()
    window._close_current_tab = MagicMock()
    window._on_close = MagicMock()
    window._clear_selected_rows = MagicMock()
    window._refresh_nicknames = MagicMock()
    window._refresh_file_list = MagicMock()
    window._toggle_nav = MagicMock()
    window._toggle_modbus_toolbar = MagicMock()
    window._modbus_toolbar_var = FakeVar(True)
    window._connect_modbus = MagicMock()
    window._disconnect_modbus = MagicMock()

    window._create_menu()

    assert window.connection_menu.commands["Connect"] == window._connect_modbus
    assert window.connection_menu.commands["Disconnect"] == window._disconnect_modbus


def test_connect_pushes_active_tab_poll_addresses_immediately():
    panel = FakePanel("one", poll_addresses=["X001", "DS1"])
    window = _make_window_stub([panel], connected=False)
    service = FakeModbusService()
    window._modbus = service
    window._ensure_modbus_service = lambda: service

    window._connect_modbus()

    assert service.connect_calls == [("127.0.0.1", 502)]
    assert service.set_poll_calls == [["X001", "DS1"]]


def test_connect_with_no_active_tab_clears_poll_addresses():
    window = _make_window_stub([], connected=False)
    service = FakeModbusService()
    window._modbus = service
    window._ensure_modbus_service = lambda: service

    window._connect_modbus()

    assert service.connect_calls == [("127.0.0.1", 502)]
    assert service.clear_poll_calls == 1


def test_tab_change_clears_hidden_live_and_replaces_poll_list():
    panel1 = FakePanel("one", poll_addresses=["X001"])
    panel2 = FakePanel("two", poll_addresses=["DS1"])
    window = _make_window_stub([panel1, panel2], connected=True)
    window.notebook.set_current_index(1)

    window._on_tab_changed(None)

    assert panel1.live_cleared == 1
    assert window._modbus.set_poll_calls[-1] == ["DS1"]


def test_address_edits_refresh_only_for_active_tab():
    panel1 = FakePanel("one", poll_addresses=["X001"])
    panel2 = FakePanel("two", poll_addresses=["DS1"])
    window = _make_window_stub([panel1, panel2], connected=True)

    window._on_panel_addresses_changed(panel1)
    assert window._modbus.set_poll_calls == [["X001"]]

    window._on_panel_addresses_changed(panel2)
    assert window._modbus.set_poll_calls == [["X001"]]


def test_closing_last_tab_clears_poll_addresses():
    panel = FakePanel("one", poll_addresses=["X001"])
    window = _make_window_stub([panel], connected=True)
    window._pending_closed_panel = panel
    window.notebook._ids = []
    window.notebook._panel_map = {}
    window.notebook._selected = ""

    window._on_tab_closed(None)

    assert panel.live_cleared == 1
    assert panel.destroyed is True
    assert window._modbus.clear_poll_calls == 1


def test_modbus_callbacks_are_marshaled_via_after():
    window = _make_window_stub([], connected=False)

    window._on_modbus_state_callback(ConnectionState.CONNECTED, None)
    window._on_modbus_values_callback({"X001": True})

    assert window.after.call_count == 2
    for call in window.after.call_args_list:
        assert call.args[0] == 0
        assert callable(call.args[1])


def test_write_actions_send_payload_and_clear_checks_on_success():
    panel = FakePanel(
        "one",
        write_rows=[("X001", True)],
        write_all_rows=[("DS1", 12)],
    )
    window = _make_window_stub([panel], connected=True)

    window._write_checked()
    window._write_all()

    assert window._modbus.write_calls == [[("X001", True)], [("DS1", 12)]]
    assert panel.write_checks_cleared == 2


def test_disconnect_dispatches_work_to_background_worker():
    panel = FakePanel("one")
    window = _make_window_stub([panel], connected=True)

    scheduled = {}

    def _capture(target, *args):
        scheduled["target"] = target
        scheduled["args"] = args

    window._run_background = _capture

    window._disconnect_modbus()

    assert window._modbus.disconnect_calls == 0
    assert window._modbus_busy is True
    assert panel.live_cleared == 1
    assert callable(scheduled["target"])
    assert scheduled["args"] == ()

    scheduled["target"](*scheduled["args"])
    assert window._modbus.disconnect_calls == 1
    assert window._modbus_busy is False


def test_write_dispatches_work_to_background_worker():
    panel = FakePanel("one", write_rows=[("X001", True)])
    window = _make_window_stub([panel], connected=True)

    scheduled = {}

    def _capture(target, *args):
        scheduled["target"] = target
        scheduled["args"] = args

    window._run_background = _capture

    window._write_checked()

    assert window._modbus.write_calls == []
    assert window._modbus_write_busy is True
    assert callable(scheduled["target"])
    assert scheduled["args"] == ()

    scheduled["target"](*scheduled["args"])
    assert window._modbus.write_calls == [[("X001", True)]]
    assert window._modbus_write_busy is False


def test_disconnect_clears_poll_and_live_values():
    panel1 = FakePanel("one")
    panel2 = FakePanel("two")
    window = _make_window_stub([panel1, panel2], connected=True)

    window._disconnect_modbus()

    assert window._modbus.clear_poll_calls >= 1
    assert window._modbus.disconnect_calls == 1
    assert panel1.live_cleared == 1
    assert panel2.live_cleared == 1
