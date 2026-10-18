"""What the simulator remembers between sessions.

Switch positions, Momentary/Maintained choices, analog values, forces and
whether the RUN hint has been seen. Before a durable workspace is paired the
file lives in ``%LOCALAPPDATA%\\ClickNick\\simulator\\<PLC name>.toml``; once one
is paired it moves to ``<workspace>/simulator.toml`` so it travels with the
engineering work.
"""

from __future__ import annotations

import os
import re
import tempfile
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import tomlkit
from pyclickplc.addresses import normalize_address

PlcValue = bool | int | float | str

STATE_FILENAME = "simulator.toml"
DEFAULT_MODBUS_PORT = 502
_VERSION = 1


@dataclass(frozen=True)
class SimulatorState:
    """The simulator's remembered settings. Keys are CLICK display addresses."""

    switches: Mapping[str, bool] = field(default_factory=dict)
    momentary: frozenset[str] = frozenset()
    analog: Mapping[str, float] = field(default_factory=dict)
    forces: Mapping[str, PlcValue] = field(default_factory=dict)
    run_hint_seen: bool = False
    modbus_port: int = DEFAULT_MODBUS_PORT
    modules: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestoreResult:
    """A state trimmed to the hardware and addresses that still exist."""

    state: SimulatorState
    dropped: tuple[str, ...] = ()
    hardware_changed: bool = False


def app_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "ClickNick" / "simulator"


def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "unnamed"


def app_data_state_path(plc_name: str, *, root: Path | None = None) -> Path:
    return (root or app_data_dir()) / f"{_safe_name(plc_name)}.toml"


def workspace_state_path(workspace_dir: Path) -> Path:
    return workspace_dir / STATE_FILENAME


def _address(value: object) -> str | None:
    return normalize_address(value) if isinstance(value, str) else None


def _parse(data: Mapping[str, object]) -> SimulatorState:
    def table(name: str) -> Mapping[str, object]:
        value = data.get(name, {})
        return value if isinstance(value, Mapping) else {}

    switches = {
        address: value
        for key, value in table("switches").items()
        if isinstance(value, bool) and (address := _address(key))
    }
    momentary = frozenset(
        address
        for key, value in table("input_modes").items()
        if value == "momentary" and (address := _address(key))
    )
    analog = {
        address: float(value)
        for key, value in table("analog").items()
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and (address := _address(key))
    }
    forces = {
        address: value
        for key, value in table("forces").items()
        if isinstance(value, bool | int | float | str) and (address := _address(key))
    }
    port = data.get("modbus_port", DEFAULT_MODBUS_PORT)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        port = DEFAULT_MODBUS_PORT
    modules = data.get("modules", ())
    return SimulatorState(
        switches=switches,
        momentary=momentary,
        analog=analog,
        forces=forces,
        run_hint_seen=data.get("run_hint_seen") is True,
        modbus_port=port,
        modules=tuple(m for m in modules if isinstance(m, str))
        if isinstance(modules, list)
        else (),
    )


def load_state(path: Path) -> SimulatorState:
    """Read a state file. A missing file is an empty state.

    Raises ValueError for a file that is not valid TOML and OSError if it
    cannot be read. Unknown or malformed entries are skipped.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return SimulatorState()
    try:
        return _parse(tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid simulator state file: {path}") from exc


def _sorted_items(values: Mapping[str, object]) -> list[tuple[str, object]]:
    from .sim_hardware import address_sort_key

    return sorted(values.items(), key=lambda item: address_sort_key(item[0]))


def dump_state(state: SimulatorState) -> str:
    doc = tomlkit.document()
    doc.add(tomlkit.comment("ClickNick simulator state. Safe to delete."))
    doc["version"] = _VERSION
    doc["run_hint_seen"] = state.run_hint_seen
    doc["modbus_port"] = state.modbus_port
    doc["modules"] = list(state.modules)
    for name, values in (
        ("switches", state.switches),
        ("input_modes", {address: "momentary" for address in state.momentary}),
        ("analog", state.analog),
        ("forces", state.forces),
    ):
        section = tomlkit.table()
        for key, value in _sorted_items(values):
            section[key] = value
        doc[name] = section
    return tomlkit.dumps(doc)


def save_state(path: Path, state: SimulatorState) -> None:
    """Write *state* atomically, creating the folder if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_value = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    staging = Path(staging_value)
    try:
        staging.write_text(dump_state(state), encoding="utf-8")
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


@dataclass(frozen=True)
class StateFile:
    """Where the state lives now, and anything the user should be told about the move."""

    path: Path
    notice: str | None = None


def settle_state_file(
    plc_name: str, workspace_dir: Path | None, *, app_data_root: Path | None = None
) -> StateFile:
    """Pick the state file, moving the app-data copy into a newly paired workspace.

    When a workspace already has its own ``simulator.toml``, that copy wins
    and the app-data copy is deleted.
    """
    app_path = app_data_state_path(plc_name, root=app_data_root)
    if workspace_dir is None:
        return StateFile(app_path)

    target = workspace_state_path(workspace_dir)
    if not app_path.is_file():
        return StateFile(target)
    if target.is_file():
        app_path.unlink(missing_ok=True)
        return StateFile(
            target,
            "This workspace already had simulator settings, so ClickNick is using "
            "them instead of the ones saved before the workspace was set up.",
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        app_path.replace(target)
    except OSError:
        # A copy across drives cannot be renamed; fall back to copy + delete.
        target.write_bytes(app_path.read_bytes())
        app_path.unlink(missing_ok=True)
    return StateFile(target)


def adopt_snapshot(
    state: SimulatorState,
    snapshot: Mapping[str, PlcValue],
    *,
    inputs: Iterable[str],
    analog_inputs: Iterable[str],
) -> SimulatorState:
    """Set switches and analog inputs to a PLC data dump's values (the snapshot wins).

    Momentary inputs keep no position, so they are left alone; forces too.
    """
    switches = dict(state.switches)
    for address in inputs:
        if address in state.momentary or address not in snapshot:
            continue
        if snapshot[address]:
            switches[address] = True
        else:
            switches.pop(address, None)
    analog = dict(state.analog)
    for address in analog_inputs:
        value = snapshot.get(address)
        if isinstance(value, int | float) and not isinstance(value, bool):
            analog[address] = float(value)
    return replace(state, switches=switches, analog=analog)


def restore_state(
    state: SimulatorState,
    *,
    inputs: Iterable[str],
    analog_inputs: Iterable[str],
    modules: tuple[str, ...],
) -> RestoreResult:
    """Keep only entries whose addresses the current hardware still provides.

    Forces may target any CLICK address, so they are kept as long as the
    address is valid. The module list is updated to *modules*.
    """
    input_set = set(inputs)
    analog_set = set(analog_inputs)
    dropped: list[str] = []

    def keep(address: str, allowed: set[str]) -> bool:
        if address in allowed:
            return True
        dropped.append(address)
        return False

    switches = {a: v for a, v in state.switches.items() if keep(a, input_set)}
    momentary = frozenset(a for a in state.momentary if a in input_set)
    analog = {a: v for a, v in state.analog.items() if keep(a, analog_set)}
    forces = {a: v for a, v in state.forces.items() if normalize_address(a) == a}
    dropped.extend(a for a in state.forces if a not in forces)
    hardware_changed = bool(state.modules) and tuple(state.modules) != tuple(modules)
    trimmed = replace(
        state,
        switches=switches,
        momentary=momentary,
        analog=analog,
        forces=forces,
        modules=tuple(modules),
    )
    return RestoreResult(trimmed, tuple(dict.fromkeys(dropped)), hardware_changed=hardware_changed)
