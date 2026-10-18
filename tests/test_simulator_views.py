"""The Console, Simulator window and Dataview panel as observers of one SimulationSession."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pyclickplc.addresses import get_addr_key

tk = pytest.importorskip("tkinter")

from test_simulation_session import Harness, _ready_analysis  # noqa: E402

from clicknick.services.analysis_service import AnalysisService  # noqa: E402
from clicknick.simulation_session import SimStatus  # noqa: E402


@pytest.fixture(scope="module")
def tk_root():
    """One root for the whole module (per-test roots fail intermittently)."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display available: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture()
def ready(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return Harness(tmp_path, _ready_analysis(project))


@pytest.fixture()
def console(tk_root, monkeypatch):
    from clicknick.views.console_window import ConsoleWindow

    monkeypatch.setattr(ConsoleWindow, "_start_background", lambda _self, _t, *, name: None)
    built = []

    def make(harness, *, turn_on=True):
        win = ConsoleWindow(tk_root, simulation=harness.sim, get_analysis=lambda: harness.analysis)
        if turn_on:  # what the app does after opening the window
            harness.sim.turn_on()
        harness.scheduler.run_ready()
        built.append(win)
        win.update_idletasks()
        return win

    yield make
    for win in built:
        win._on_close()


def _output(win) -> str:
    return win._output.get("1.0", "end-1c")


def test_console_shows_startup_and_follows_the_session(console, ready):
    win = console(ready)
    assert ready.sim.is_ready
    assert "OK - simulation ready." in _output(win)
    assert win._status_var.get() == "STOP | Scan 0"
    assert not win._retry_btn.winfo_manager()

    win._on_close()
    assert ready.sim.is_ready, "closing the window leaves the simulation running"


def test_console_offers_start_while_the_simulation_is_off(console, ready):
    win = console(ready)
    ready.sim.turn_off()
    win.update_idletasks()
    assert win._status_var.get() == "Simulation off"
    assert win._retry_btn.winfo_manager()
    assert win._retry_btn.cget("text") == "Start"

    win._retry_btn.invoke()
    ready.scheduler.run_ready()
    assert ready.sim.is_ready
    assert not win._retry_btn.winfo_manager()


def test_console_offers_retry_and_details_for_a_failed_conversion(console, tmp_path):
    svc = AnalysisService()
    svc.mark_failed("pyrung conversion crashed", "Traceback...\nValueError: boom")
    harness = Harness(tmp_path, svc)
    win = console(harness)

    assert harness.sim.status is SimStatus.FAILED
    assert win._retry_btn.winfo_manager()
    assert "pyrung conversion crashed" in _output(win)
    assert "Traceback" not in _output(win)
    assert win._details_btn.winfo_manager()

    win._details_btn.invoke()
    assert "Traceback...\nValueError: boom" in _output(win)
    assert not win._details_btn.winfo_manager()

    win._retry_btn.invoke()
    assert harness.retries == ["rebuild"]


@pytest.fixture()
def simulator(tk_root):
    from clicknick.views.simulator_window import SimulatorWindow

    built = []

    def make(harness, store=None, *, turn_on=True):
        win = SimulatorWindow(
            tk_root,
            simulation=harness.sim,
            get_store=lambda: store,
            open_dataview=lambda: None,
            open_console=lambda: None,
        )
        if turn_on:
            harness.sim.turn_on()
        harness.scheduler.run_ready()
        built.append(win)
        win.update_idletasks()
        return win

    yield make
    for win in built:
        win._on_close()


def test_simulator_draws_the_rack_and_drives_the_session(simulator, ready):
    win = simulator(ready)
    assert set(win._inputs) == {"X001", "X002", "X003"}
    assert set(win._outputs) == {"Y001"}
    assert set(win._analog_in) == {"DF1"}
    assert ready.modbus[-1].polled  # the panel's addresses are polled

    win._on_switch_press("X001")
    assert ready.sim.switch_on("X001")
    assert ready.modbus[-1].writes[-1] == [("X001", True)]

    ready.sim.set_momentary("X002", True)
    win._on_switch_press("X002")
    assert ready.sim.switch_on("X002")
    win._on_any_release(None)
    assert not ready.sim.switch_on("X002")


def test_mode_switch_clicks_and_step_controls(simulator, ready):
    win = simulator(ready)
    sx, sy, zone = win._mode_zone
    ready.dap.calls.clear()
    win._on_mode_click(SimpleNamespace(x=sx + 2.5 * zone, y=sy + 10))
    assert ("set_mode", "run", {}, None) in ready.dap.calls
    assert ("continue",) in ready.dap.calls

    ready.dap.frame(mode="run", running=False, source={"origin": "live", "command": "step"})
    ready.scheduler.run_ready()
    win.update_idletasks()
    assert win._step_bar.winfo_manager()
    assert not win._run_bar.winfo_manager()
    assert win._status_var.get() == "Moved to STEP by Console: step"

    ready.dap.frame(mode="run", running=True, source={})
    ready.scheduler.run_ready()
    win.update_idletasks()
    assert win._run_bar.winfo_manager()
    assert not win._step_bar.winfo_manager()


def test_restored_forces_banner_and_badges(simulator, ready):
    ready.sim.force("Y001", True)
    ready.sim._restored_forces = 1
    win = simulator(ready)
    assert "1 force restored" in str(win._banner_key)
    badge = win._outputs["Y001"]["badge"]
    assert win._canvas.itemcget(badge[1], "state") == "normal"

    ready.sim.release_all_forces()
    assert win._banner_key == ()
    assert win._canvas.itemcget(badge[1], "state") == "hidden"


def test_simulator_without_cpu_shows_the_placeholder(simulator, ready):
    from clicknick.services.sim_hardware import build_panel_layout

    ready.sim._layout_reader = lambda _p, used: build_panel_layout((), used)
    win = simulator(ready)
    texts = [
        win._canvas.itemcget(item, "text")
        for item in win._canvas.find_all()
        if win._canvas.type(item) == "text"
    ]
    assert any(t.startswith("No CPU configured.") for t in texts)


def test_dataview_force_column(tk_root):
    from pyclickplc.addresses import normalize_address

    from clicknick.views.dataview_editor.panel import COL_FORCE, DataviewPanel

    forced: list = []
    panel = DataviewPanel(
        tk_root,
        address_normalizer=normalize_address,
        on_force=lambda address, value: forced.append((address, value)),
    )
    try:
        panel.add_address("Y001")
        panel.set_force_column_visible(True)
        assert COL_FORCE in panel.sheet.MT.displayed_columns

        panel._apply_force_edit(0, "1")
        assert forced == [("Y001", True)]
        assert panel.sheet.get_cell_data(0, COL_FORCE) == "", "only the session's forces show"

        panel.update_forces({"Y001": True})
        assert panel.sheet.get_cell_data(0, COL_FORCE) != ""
        panel._apply_force_edit(0, "")
        assert forced[-1] == ("Y001", None)

        panel.set_force_column_visible(False)
        assert COL_FORCE not in panel.sheet.MT.displayed_columns
    finally:
        panel.destroy()


def test_simulator_stays_open_with_start_when_turned_off(simulator, ready):
    win = simulator(ready)
    ready.sim.turn_off()
    assert any("Simulation is off" in text for text, _labels in win._banner_key)
    assert set(win._inputs) == {"X001", "X002", "X003"}, "the hardware still shows"
    ready.sim.turn_on()
    ready.scheduler.run_ready()
    assert ready.sim.is_ready
    assert not any("Simulation is off" in text for text, _labels in win._banner_key)


def test_simulator_shows_nicknames_with_full_text_on_hover(simulator, ready):
    rows = {
        get_addr_key("X", 1): SimpleNamespace(nickname="Start_PB"),
        get_addr_key("Y", 1): SimpleNamespace(nickname="Conveyor_Motor_Run_Output_Long"),
    }
    store = SimpleNamespace(
        visible_state=rows, add_observer=lambda _cb: None, remove_observer=lambda _cb: None
    )
    win = simulator(ready, store)
    texts = [
        win._canvas.itemcget(item, "text")
        for item in win._canvas.find_all()
        if win._canvas.type(item) == "text"
    ]
    assert "Start_PB" in texts
    assert any(t.startswith("Conveyor") and t.endswith("\N{HORIZONTAL ELLIPSIS}") for t in texts)
    assert "Conveyor_Motor_Run_Output_Long" not in texts
