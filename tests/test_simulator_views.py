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
    assert ready.dap.calls[-1] == ("patch", {"X001": True})

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


# ----------------------------------------------------------------------
# Feedback links
# ----------------------------------------------------------------------


class _Session:
    def __init__(self, store) -> None:
        self.store = store

    def set_field(self, addr_key, field, value) -> None:
        self.store.edits.append((addr_key, field, value))
        row = self.store.visible_state[addr_key]
        self.store.visible_state[addr_key] = SimpleNamespace(**{**vars(row), field: value})

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None


class _Store:
    def __init__(self, rows) -> None:
        self.visible_state = rows
        self.edits: list = []

    def add_observer(self, _cb) -> None: ...

    def remove_observer(self, _cb) -> None: ...

    def edit_session(self, _description):
        return _Session(self)


def _frame(harness) -> None:
    harness.dap.links_revision += 1
    harness.dap.frame()
    harness.scheduler.run_ready()


def _menu_labels(menu) -> list[str]:
    end = menu.index("end")
    return [
        menu.entrycget(i, "label")
        for i in range(0 if end is None else end + 1)
        if menu.type(i) != "separator"
    ]


def test_a_linked_input_shows_its_driver_instead_of_a_switch(simulator, ready):
    from clicknick.services.sim_state import BenchLink
    from clicknick.views import sim_palette as P

    ready.sim.link("X002", BenchLink("Y001", on_delay="1s"))
    win = simulator(ready)
    ready.dap.project["X003"] = "Y001"
    _frame(ready)
    c = win._canvas

    bench, project, free = win._inputs["X002"], win._inputs["X003"], win._inputs["X001"]
    assert c.itemcget(bench["pill"], "state") == "normal"
    assert c.itemcget(bench["pill_text"], "text") == "Y001"
    assert c.itemcget(bench["pill"], "fill") == P.LINK_BENCH
    assert c.itemcget(bench["track"], "state") == "hidden"
    assert c.itemcget(project["pill"], "fill") == P.LINK
    assert c.itemcget(free["pill"], "state") == "hidden"
    assert win._link_text("X002").startswith("Bench link: driven by Y001 (1s).")
    assert win._link_text("X003").startswith("Program link: driven by Y001 (1s).")

    win._show_wire("X002")
    assert len(c.find_withtag("wire")) == 2


def test_a_cut_link_gives_the_switch_back(simulator, ready):
    win = simulator(ready)
    ready.dap.project["X003"] = "Y001"
    _frame(ready)
    ready.sim.cut_link("X003")
    _frame(ready)
    info = win._inputs["X003"]
    assert win._canvas.itemcget(info["pill"], "state") == "hidden"
    assert win._canvas.itemcget(info["track"], "state") == "normal"
    assert win._canvas.itemcget(info["cut"], "state") == "normal"


def test_link_menu_items_follow_the_link(simulator, ready, tk_root):
    win = simulator(ready)
    ready.dap.project["X003"] = "Y001"
    _frame(ready)

    def labels(address):
        menu = tk.Menu(tk_root, tearoff=0)
        win._add_link_items(menu, address, analog=False)
        return _menu_labels(menu)

    assert labels("X001") == ["Link to the tag that drives it..."]
    assert labels("X003") == ["Change link on the bench...", "Cut link (simulate a failure)"]
    ready.sim.cut_link("X003")
    assert labels("X003") == ["Restore the program's link"]


def test_save_link_to_project_writes_the_comment(simulator, ready):
    from clicknick.services.sim_state import BenchLink

    aux, motor = get_addr_key("X", 2), get_addr_key("Y", 1)
    store = _Store(
        {
            aux: SimpleNamespace(nickname="Aux", comment="Aux contact"),
            motor: SimpleNamespace(nickname="Motor", comment=""),
        }
    )
    ready.sim.link("X002", BenchLink("Y001", on_delay="1s"))
    win = simulator(ready, store)

    win._save_link_to_project("X002")
    assert store.edits == [(aux, "comment", "[link=Motor, on_delay=1s] Aux contact")]
    assert "Saved the link on X002 to the project" in str(win._banner_key)
    assert win._saved_to_project("X002", ready.sim.bench_links["X002"])


def test_save_link_needs_a_nickname(simulator, ready, monkeypatch):
    from clicknick.services.sim_state import BenchLink

    store = _Store({get_addr_key("X", 2): SimpleNamespace(nickname="", comment="")})
    ready.sim.link("X002", BenchLink("Y001", on_delay="1s"))
    win = simulator(ready, store)
    errors: list[str] = []
    monkeypatch.setattr(win, "_show_action_error", errors.append)
    win._save_link_to_project("X002")
    assert store.edits == []
    assert errors and "nickname first" in errors[0]


def test_wiring_menu_lists_links_and_turns_bench_wiring_off(simulator, ready):
    from clicknick.services.sim_state import BenchLink

    ready.sim.link("X002", BenchLink("Y001", on_delay="1s"))
    win = simulator(ready)
    ready.dap.project["X003"] = "Y001"
    _frame(ready)
    assert win._wiring_btn.cget("text") == "Wiring (1 bench)"

    win._populate_wiring_menu()
    labels = _menu_labels(win._wiring_menu)
    assert labels[0] == "Apply bench links"
    assert any(label.startswith("X003") and "program" in label for label in labels)
    assert any(label.startswith("X002") and label.endswith("bench") for label in labels)

    win._wiring_menu.invoke(0)
    assert ready.sim.bench_wiring is False
    assert ready.dap.calls[-1] == ("set_links", False, {})


def test_restored_links_banner(simulator, ready):
    from clicknick.services.sim_state import BenchLink

    ready.sim.link("X002", BenchLink("Y001", on_delay="1s"))
    ready.sim._restored_links = 1
    win = simulator(ready)
    assert "1 bench link restored" in str(win._banner_key)
    ready.sim.discard_bench_links()
    assert "bench link restored" not in str(win._banner_key)


def test_link_dialog_builds_bench_links(tk_root):
    from clicknick.services.sim_state import BenchLink
    from clicknick.views.sim_link_dialog import LinkDialog

    linked: list = []
    dialog = LinkDialog(
        tk_root, feedback="X002", analog=False, current=None, enables=["Y001"],
        on_ok=linked.append,
    )  # fmt: skip
    try:
        dialog._enable_var.set("y1")
        dialog._first_var.set("2s")
        dialog._second_var.set("")
        assert dialog.build() == BenchLink("Y001", on_delay="2s")
        dialog._trigger_var.set("2")
        dialog._kind_var.set("pulse")
        dialog._on_kind_changed()
        assert dialog.build() == BenchLink(
            "Y001", 2, profile="pulse:on_dwell=500ms|off_dwell=500ms"
        )
        dialog._enable_var.set("nowhere")
        with pytest.raises(ValueError, match="CLICK address"):
            dialog.build()
    finally:
        dialog.destroy()

    dialog = LinkDialog(
        tk_root, feedback="DF1", analog=True,
        current=BenchLink("Y002", profile="ramp:up=2.0|down=-1.0"), enables=[],
        on_ok=linked.append,
    )  # fmt: skip
    try:
        assert dialog._kind_var.get() == "ramp"
        assert (dialog._first_var.get(), dialog._second_var.get()) == ("2.0", "-1.0")
        dialog._accept()
        assert linked == [BenchLink("Y002", profile="ramp:up=2.0|down=-1.0")]
    finally:
        if dialog.winfo_exists():
            dialog.destroy()
