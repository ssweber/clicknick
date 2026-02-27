# Plan: ClickNick Dataview Live Integration Requirements

## Scope

This plan now covers only ClickNick-side requirements.

`ModbusService` implementation and service-level batching behavior are planned in:

- `../pyclickplc/scratchpad/modbus-service-plan.md`

ClickNick should treat that service as an external dependency and only integrate against its public API.

## Required pyclickplc API

ClickNick integration assumes `pyclickplc` provides:

- `ConnectionState`
- `ModbusService`
- `set_poll_addresses(addresses: Iterable[str])`
- `clear_poll_addresses()`
- `write(values: Mapping[str, PlcValue] | Iterable[tuple[str, PlcValue]])`
- service callbacks for state and values

## ClickNick Requirements

### 1. DataviewPanel UI + data flow

File: `src/clicknick/views/dataview_editor/panel.py`

- Show 6 columns:
  - `Address`
  - `Nickname`
  - `Comment`
  - `New Value` (editable for writable rows only)
  - `Write` (checkbox)
  - `Live` (read-only)
- Use explicit `DataViewFile` helpers for New Value and Live formatting/parsing:
  - `DataViewFile.value_to_display(...)` for UI display text
  - `DataViewFile.validate_row_display(...)` for edit validation
  - `DataViewFile.try_parse_display(...)` or `DataViewFile.set_row_new_value_from_display(...)` for native value updates
- Keep write checkboxes only on writable, non-empty-address rows.
- Keep `New Value` effectively read-only for non-writable addresses.

Panel methods required by window integration:

- `get_poll_addresses() -> list[str]`:
  - must return only valid, non-empty, canonical-uppercase addresses
  - must deduplicate while preserving row order
- `update_live_values(values: Mapping[str, PlcValue]) -> None`
- `clear_live_values() -> None`
- `get_write_rows() -> list[tuple[str, PlcValue]]` (checked + writable only)
- `get_write_all_rows() -> list[tuple[str, PlcValue]]` (all writable rows with non-empty new value)
- `clear_write_checks() -> None`

### 2. DataviewEditorWindow integration

File: `src/clicknick/views/dataview_editor/window.py`

- Add a dedicated `Modbus` toolbar section in the main Dataview window (primary connection UX):
  - `Host` input
  - `Port` input
  - `Connect/Disconnect` toggle button
  - connection state indicator text
  - optional last-error text
- Add `Connection` menu:
  - `Connect`
  - `Disconnect`
- Do not add separate connect/disconnect windows; connection controls live in the toolbar.
- Keep `Connection` menu as secondary entry points that call the same toolbar-backed handlers and use current toolbar host/port values.
- Own a service instance:
  - `self._modbus: ModbusService | None`
- On connect:
  - wire `on_state` and `on_values` callbacks
  - marshal callback UI updates with `self.after(0, ...)`
  - immediately sync poll addresses from the currently visible tab after successful connect
  - if there is no visible tab, call `self._modbus.clear_poll_addresses()`
- On tab change:
  - clear `Live` values in the tab being hidden
  - replace poll list with newly active tab addresses
  - if there is no active tab, call `self._modbus.clear_poll_addresses()`
- On tab close:
  - if the closed tab was active, recompute from new active tab and replace poll list
  - if no tabs remain, call `self._modbus.clear_poll_addresses()`
- On address edits:
  - if edit happened in active tab, replace poll list with active tab addresses
  - if edit happened in inactive tab, do not change poll list
- Add toolbar actions:
  - `Write Checked`: send `panel.get_write_rows()`
  - `Write All`: send `panel.get_write_all_rows()`
  - both disabled unless connected
  - grouped with Modbus connect controls in the same toolbar region
- On successful write completion:
  - call `panel.clear_write_checks()`
- On disconnect:
  - call `self._modbus.clear_poll_addresses()` before disconnect (or equivalent stop behavior)
  - clear live values in all open panels
- On window close:
  - call `self._modbus.disconnect()` before destroy

### 3. Write behavior requirements

- `Write Checked` writes only checked writable rows.
- `Write All` writes all writable rows with non-empty `new_value`.
- Non-writable rows must never be included in ClickNick write payloads.
- ClickNick payload should be address + native value only; service owns protocol/write strategy.

### 4. Poll behavior requirements

- Poll list is replace-based per active context, not additive subscription.
- Only the currently visible tab is polled.
- Hidden tabs are never polled.
- Active tab fully controls poll list (single source of truth).
- Connect immediately syncs poll list from active tab (no user action required).
- Address edits in active tab refresh poll list; edits in inactive tabs do not.
- Switching away from a tab clears that tab's `Live` values.
- No active tab (for example, last tab closed) must clear poll addresses in service.
- Disconnect clears live display values in all open tabs.

## ClickNick Test Requirements

1. Panel behavior
- New Value edit validation and normalization uses `DataViewFile` helpers.
- Write checkbox lifecycle tracks writability/address presence.
- `get_write_rows()` and `get_write_all_rows()` include only writable rows.
- `get_poll_addresses()` returns canonical uppercase, valid-only, de-duplicated addresses.

2. Window integration
- Mocks `pyclickplc.ModbusService`.
- Verifies Modbus toolbar controls drive connect/disconnect handlers.
- Verifies `Connection` menu entries call the same handlers as toolbar controls.
- Verifies connect immediately pushes active tab poll list.
- Verifies tab change replaces poll list and clears hidden tab live values.
- Verifies active-tab address edits call `set_poll_addresses(...)`.
- Verifies inactive-tab address edits do not call `set_poll_addresses(...)`.
- Verifies closing active/last tab clears poll addresses.
- Verifies no-tab state calls `clear_poll_addresses()`.
- Verifies state/value callbacks are marshaled via `after(...)`.
- Verifies write actions call service with expected payloads.
- Verifies connect/disconnect button/menu enablement and cleanup.

Suggested file:

- `tests/test_dataview_modbus_integration.py`

## Files (ClickNick only)

- `src/clicknick/views/dataview_editor/panel.py`
- `src/clicknick/views/dataview_editor/window.py`
- `tests/test_dataview_modbus_integration.py`

## Verification (ClickNick)

1. `make lint`
2. `make test`
3. Manual:
   - Open `.cdv` -> 6 columns visible
   - Modbus toolbar visible with host/port + connect controls
   - Edit `New Value` -> valid normalization + invalid rejection
   - Connect from toolbar -> active tab starts live polling immediately
   - Tab change -> previous tab live values clear; new active tab values populate
   - Active-tab address change -> poll list updates immediately
   - Close last tab -> polling stops
   - Write Checked -> only checked writable rows written
   - Write All -> only writable rows with values written
   - Disconnect/close -> live values cleared and service disconnected
