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
- Use `DataviewFile` helpers for new-value validation/parse/display normalization.
- Keep write checkboxes only on writable, non-empty-address rows.
- Keep `New Value` effectively read-only for non-writable addresses.

Panel methods required by window integration:

- `get_poll_addresses() -> list[str]`
- `update_live_values(values: Mapping[str, PlcValue]) -> None`
- `clear_live_values() -> None`
- `get_write_rows() -> list[tuple[str, PlcValue]]` (checked + writable only)
- `get_write_all_rows() -> list[tuple[str, PlcValue]]` (all writable rows with non-empty new value)
- `clear_write_checks() -> None`

### 2. DataviewEditorWindow integration

File: `src/clicknick/views/dataview_editor/window.py`

- Add `Connection` menu:
  - `Connect...`
  - `Disconnect`
- Add simple host/port connect dialog.
- Own a service instance:
  - `self._modbus: ModbusService | None`
- On connect:
  - wire `on_state` and `on_values` callbacks
  - marshal callback UI updates with `self.after(0, ...)`
- On tab change and address edits:
  - call `self._modbus.set_poll_addresses(panel.get_poll_addresses())`
- Add toolbar actions:
  - `Write Checked`: send `panel.get_write_rows()`
  - `Write All`: send `panel.get_write_all_rows()`
  - both disabled unless connected
- On successful write completion:
  - call `panel.clear_write_checks()`
- On disconnect:
  - clear live values in active panel
- On window close:
  - call `self._modbus.disconnect()` before destroy

### 3. Write behavior requirements

- `Write Checked` writes only checked writable rows.
- `Write All` writes all writable rows with non-empty `new_value`.
- Non-writable rows must never be included in ClickNick write payloads.
- ClickNick payload should be address + native value only; service owns protocol/write strategy.

### 4. Poll behavior requirements

- Poll list is replace-based per active context, not additive subscription.
- Active tab controls the poll list.
- Address edits in active tab refresh the poll list.
- Disconnect clears live display values.

## ClickNick Test Requirements

1. Panel behavior
- New Value edit validation and normalization uses `DataviewFile` helpers.
- Write checkbox lifecycle tracks writability/address presence.
- `get_write_rows()` and `get_write_all_rows()` include only writable rows.

2. Window integration
- Mocks `pyclickplc.ModbusService`.
- Verifies tab change/address change call `set_poll_addresses(...)`.
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
   - Edit `New Value` -> valid normalization + invalid rejection
   - Connect -> live values populate
   - Tab/address changes -> poll list updates
   - Write Checked -> only checked writable rows written
   - Write All -> only writable rows with values written
   - Disconnect/close -> live values cleared and service disconnected
