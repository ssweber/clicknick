# Plan: Dataview Editor — New Value Column, Live Column, Modbus Connection

## Context

The Dataview Editor currently requires a Click.exe window to be open and only shows 3 columns (Address, Nickname, Comment). The `DataviewRow.new_value` field exists but isn't displayed. We want to:

1. Show and edit New Value in the sheet
2. Add a read-only Live column showing real-time PLC values via Modbus
3. Add "Connect via Modbus" to the Dataview Editor
4. Relax the Click.exe requirement so the editor can open standalone

This is **Stage 1** of a multi-stage effort to decouple ClickNick from requiring Click.exe.

---

## Step 1: Add New Value, Write, and Live columns to DataviewPanel

**File: `src/clicknick/views/dataview_editor/panel.py`**

Add three columns to the tksheet:

```
COL_ADDRESS = 0
COL_NICKNAME = 1
COL_COMMENT = 2
COL_NEW_VALUE = 3   # new — editable
COL_WRITE = 4       # new — checkbox (mark rows to write)
COL_LIVE = 5        # new — read-only
```

Changes:
- Headers → `["Address", "Nickname", "Comment", "New Value", "Write", "Live"]`
- Column widths → `[80, 170, 210, 100, 45, 80]`
- Readonly columns → `[COL_NICKNAME, COL_COMMENT, COL_LIVE]` (Write column uses checkboxes, not readonly)
- `_apply_overflow_styling` → update `range(3)` to `range(6)`
- `_populate_sheet()` → append `row.new_value_display`, `False` (write checkbox), and `""` (live) per row
- After `_populate_sheet()`, create checkboxes: `self.sheet.create_checkbox(r=i, c=COL_WRITE, checked=False)` for each row with a writable non-empty address
- `_update_row_display()` → set cells for COL_NEW_VALUE and COL_LIVE; manage write checkbox (create/delete based on `row.is_writable` and `row.new_value`)
- `_validate_edit()` → add COL_NEW_VALUE branch: check `row.is_writable`, call `row.validate_new_value()`
- `_on_sheet_modified()` → add COL_NEW_VALUE branch: call `row.set_new_value_from_display()`, re-display normalized value
- `_pad_to_target()` / `_insert_address_at()` → set empty data for 3 new columns
- Add `import datatype_to_display` from pyclickplc.dataview

Checkbox pattern (already used in address_editor/panel.py):
```python
# Create checkbox for writable rows with new_value set
self.sheet.create_checkbox(r=row_idx, c=COL_WRITE, checked=False)
# Delete checkbox for non-writable/empty rows
self.sheet.delete_checkbox(row_idx, COL_WRITE)
```

New methods on DataviewPanel:
- `update_live_values(values: dict[str, PlcValue])` — update Live column cells from poll results
- `clear_live_values()` — blank all Live cells (on disconnect)
- `get_poll_addresses() -> list[str]` — return non-empty addresses for Modbus polling
- `get_write_rows() -> list[tuple[str, DataType, str]]` — return (address, data_type, new_value_storage) for checked rows
- `clear_write_checks()` — uncheck all Write checkboxes after successful write

New instance state:
- `self._live_values: dict[int, str] = {}` — row_idx → display string cache

Per-cell readonly for New Value on non-writable rows (XD, YD, read-only SC/SD).

---

## Step 2: Create ModbusService (async-to-sync bridge)

**New file: `src/clicknick/services/modbus_service.py`**

Bridges async `ClickClient` with synchronous tkinter via a background daemon thread running an asyncio event loop.

```python
class ConnectionState(Enum):
    DISCONNECTED / CONNECTING / CONNECTED / ERROR

class ModbusService:
    # Sync API for tkinter callers
    def connect(host, port, on_state, on_values) -> None
    def disconnect() -> None
    def set_addresses(addresses: list[str]) -> None
    def stop_polling() -> None

    # Internal async (background thread)
    async _connect()
    async _disconnect()
    async _poll_loop()          # periodic read at ~1.5s interval
    async _read_addresses()     # bank-batched reads for efficiency
```

Key design:
- **One daemon thread** with `asyncio.new_event_loop()` — exits when main thread exits
- **`threading.Event`** gates loop readiness before scheduling coroutines
- **Callbacks** (`on_state`, `on_values`) called from background thread — window wraps with `widget.after(0, ...)` for thread safety
- **Bank-batched reads**: groups addresses by memory type, uses range reads when span < 2x count and <= 125 registers
- **Write support**: `write_values(writes: list[tuple[str, PlcValue]])` schedules async writes via `plc.addr.write(address, value)` for each checked row. Callback on completion/error.
- No auto-reconnect in Stage 1 (manual connect/disconnect only)

---

## Step 3: Integrate Modbus into DataviewEditorWindow

**File: `src/clicknick/views/dataview_editor/window.py`**

1. **Connection menu** — add to menu bar:
   - `Connection > Connect...` → opens host/port dialog
   - `Connection > Disconnect` → tears down ModbusService

2. **Connection dialog** — simple `tk.Toplevel` with host + port entries and a Connect button. Can be a private method, no separate file needed.

3. **ModbusService ownership** — `self._modbus: ModbusService | None = None` in `__init__`

4. **State change handler** — `on_state` callback from service → `self.after(0, ...)` → update status label at bottom of window

5. **Value handler** — `on_values` callback from service → `self.after(0, ...)` → call `panel.update_live_values(values)` on active panel

6. **Tab change** — in `_on_tab_changed`: call `self._modbus.set_addresses(panel.get_poll_addresses())` to switch polling to active tab's addresses

7. **Address edit hook** — add `on_addresses_changed` callback to DataviewPanel constructor. When addresses change in the sheet, window calls `self._modbus.set_addresses(...)`.

8. **Write toolbar** — add "Write Checked" and "Write All" buttons to the toolbar:
   - **Write Checked** — calls `panel.get_write_rows()` to get checked rows, converts `new_value` storage strings to native Python values via `storage_to_datatype()`, then calls `self._modbus.write_values(...)`. On completion, unchecks written rows via `panel.clear_write_checks()`.
   - **Write All** — same as Write Checked but for all rows with non-empty `new_value` (ignores checkbox state).
   - Both disabled when not connected.

9. **Connection status bar** — `ttk.Label` at bottom of content area showing connection state

10. **Cleanup** — `_on_close()` calls `self._modbus.disconnect()` before destroy

---

## Step 4: Relax Click.exe requirement

**File: `src/clicknick/app.py` — `_open_dataview_editor()`**

Remove the `connected_click_pid` guard. Allow `project_path=None` and `address_store=None`:

```python
# project_path is None when no Click.exe connected
project_path = None
if self.connected_click_pid and self.connected_click_hwnd:
    project_path = get_project_path_from_hwnd(self.connected_click_hwnd)

SharedDataviewData(
    project_path=project_path,           # None = no sidebar
    address_store=self._shared_address_data,  # None = no nickname lookup
)
```

**File: `src/clicknick/views/dataview_editor/window.py` — `_create_widgets()`**

When `shared_data.dataview_folder is None`, skip the PanedWindow sidebar layout — just show the toolbar + notebook directly. The File > Open menu already handles manual CDV opening.

Guard `_refresh_file_list()` against missing sidebar.

---

## Step 5: Tests

**Existing test updates:**
- `tests/test_dataview_model.py` — add coverage for `new_value_display`, `set_new_value_from_display()` roundtrips, `validate_new_value()` with writable/non-writable addresses (if not already covered)

**New test file: `tests/test_modbus_service.py`**
- Bank-batching logic in `_read_addresses()` (group by bank, range vs individual reads)
- State transitions (DISCONNECTED → CONNECTING → CONNECTED → DISCONNECTED)
- `set_addresses()` updates poll list without restart
- Error handling (connection failure → ERROR state)
- Mock ClickClient to avoid real network calls

---

## Files Summary

| File | Action |
|------|--------|
| `src/clicknick/views/dataview_editor/panel.py` | Modify — add 3 columns (New Value, Write checkbox, Live), editing, live display |
| `src/clicknick/services/modbus_service.py` | **New** — async-to-sync bridge, ClickClient lifecycle, polling |
| `src/clicknick/views/dataview_editor/window.py` | Modify — Connection menu/dialog, ModbusService integration, standalone mode |
| `src/clicknick/app.py` | Modify — relax Click.exe guard for Dataview Editor |
| `tests/test_modbus_service.py` | **New** — unit tests for ModbusService |
| `tests/test_dataview_model.py` | Modify — add new_value roundtrip tests |

No changes to `pyclickplc` — all needed APIs (`DataviewRow.new_value_display`, `set_new_value_from_display`, `validate_new_value`, `datatype_to_display`) already exist.

---

## Verification

1. `make lint` — passes with no errors
2. `make test` — existing + new tests pass
3. Manual: Open Dataview Editor without Click.exe → can File > Open a .cdv → sees 6 columns
4. Manual: Edit New Value cells → validates, stores, displays normalized values
5. Manual: Check Write checkboxes → Write Checked button sends values to PLC
6. Manual: Connection > Connect to a ClickServer (or real PLC) → Live column populates
7. Manual: Switch tabs → polling updates to new tab's addresses
8. Manual: Disconnect → Live column clears
