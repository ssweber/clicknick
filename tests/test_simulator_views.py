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
def simulator(tk_root, monkeypatch):
    from clicknick.views.console_panel import ConsolePanel
    from clicknick.views.simulator_window import SimulatorWindow

    monkeypatch.setattr(ConsolePanel, "_start_background", lambda _self, _t, *, name: None)
    built = []

    def make(harness, store=None, *, turn_on=True):
        win = SimulatorWindow(
            tk_root,
            simulation=harness.sim,
            get_store=lambda: store,
            get_analysis=lambda: harness.analysis,
            open_dataview=lambda: None,
        )
        if turn_on:  # what the app does after opening the window
            harness.sim.turn_on()
        harness.scheduler.run_ready()
        built.append(win)
        win.update_idletasks()
        return win

    yield make
    for win in built:
        win._on_close()


def _output(panel) -> str:
    return panel._output.get("1.0", "end-1c")


def _console_listeners(sim) -> int:
    from clicknick.views.console_panel import ConsolePanel

    return sum(isinstance(getattr(cb, "__self__", None), ConsolePanel) for cb in sim._listeners)


def test_console_pane_starts_open_with_the_startup(simulator, ready):
    win = simulator(ready)
    assert win._console_shown()
    assert "OK - simulation ready." in _output(win._console)

    win._on_close()
    assert ready.sim.is_ready, "closing the Simulator leaves the simulation running"
    assert _console_listeners(ready.sim) == 0


def test_console_pane_hides_and_pops_out_keeping_transcript_and_history(simulator, ready):
    win = simulator(ready)
    win._console._append_output("marker\n")
    win._console_history.append("why Y001")

    win._toggle_console()
    assert not win._console_shown()
    win._toggle_console()
    assert win._console_shown()

    win._console._pop_btn.invoke()
    window = win._console_window
    assert window is not None and not win._console_shown()
    assert "OK - simulation ready." in _output(win._console)
    assert "marker" in _output(win._console)
    assert win._console._console_input._history is win._console_history
    assert _console_listeners(ready.sim) == 1

    win._toggle_console()  # raises the popped-out window; nothing docks
    assert win._console_window is window

    win._console._pop_btn.invoke()  # Dock
    assert win._console_window is None and win._console_shown()
    assert "marker" in _output(win._console)
    assert _console_listeners(ready.sim) == 1


def test_plc_data_button_names_the_loaded_file(simulator, ready, tmp_path):
    win = simulator(ready)
    assert win._plc_data_btn.cget("text") == "PLC Data..."
    ready.sim._plc_data_path = tmp_path / "line1_live_values_2026_10_21.csv"
    win._refresh_toolbar()
    text = win._plc_data_btn.cget("text")
    assert text.startswith("PLC Data: line1_live_values")
    assert text.endswith("\N{HORIZONTAL ELLIPSIS}"), "long names are shortened"


def test_dragging_the_console_header_resizes_the_pane(simulator, ready):
    from clicknick.views.simulator_window import MIN_RACK_H

    win = simulator(ready)
    win.geometry("1100x760")
    win.update()
    paned = win._paned
    sash = paned.sashpos(0)
    top = paned.winfo_rooty()
    grab = top + sash + 10  # a point on the header, just under the sash

    win._resize_console(grab, True)
    win._resize_console(grab - 100, False)
    assert paned.sashpos(0) == sash - 100, "the console grows as the header is dragged up"

    win._resize_console(top - 500, False)
    assert paned.sashpos(0) == MIN_RACK_H, "the rack keeps its minimum"


def test_a_busy_console_stays_where_it_is(simulator, ready):
    win = simulator(ready)
    win._console._set_busy(True)
    assert str(win._console._pop_btn.cget("state")) == "disabled"
    win._pop_out_console()
    assert win._console_window is None and win._console_shown()
    win._console._set_busy(False)


def test_a_failed_conversion_shows_in_the_console_and_offers_retry(simulator, tmp_path):
    svc = AnalysisService()
    svc.mark_failed("pyrung conversion crashed", "Traceback...\nValueError: boom")
    harness = Harness(tmp_path, svc)
    win = simulator(harness)

    assert harness.sim.status is SimStatus.FAILED
    assert "pyrung conversion crashed" in _output(win._console)
    assert "Traceback" not in _output(win._console)
    [labels] = [labels for text, labels in win._banner_key if text.startswith("Cannot simulate")]
    assert "Retry" in labels and "Show details" in labels


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
    win._on_mode_click(SimpleNamespace(x=sx + 10, y=sy + 0.5 * zone))  # RUN, on top
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


def test_cards_widen_so_24_character_nicknames_show_in_full(simulator, ready):
    from clicknick.views.simulator_window import CARD_W

    rows = {
        get_addr_key("X", 1): SimpleNamespace(nickname="Start_PB"),
        get_addr_key("Y", 1): SimpleNamespace(nickname="Conveyor_Infeed_Gate_Sol"),
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
    assert "Conveyor_Infeed_Gate_Sol" in texts
    assert win._card_w > CARD_W


def test_slim_cpu_card_with_its_slots_as_one_housing(simulator, ready):
    from clicknick.services.sim_hardware import build_panel_layout
    from clicknick.views.simulator_window import CARD_GAP, CPU_CARD_W, HOUSING_GAP, MARGIN

    def module(location, position, model, inputs=(), outputs=()):
        return SimpleNamespace(
            location=location, position=position, module=SimpleNamespace(model=model),
            inputs=inputs, outputs=outputs, analog_inputs=(), analog_outputs=(),
        )  # fmt: skip

    modules = [
        module("cpu", 0, "C2-03CPU-2"),
        module("slot", 0, "C2-08ND3", inputs=("X001", "X002")),
        module("expansion", 1, "C0-08TD1", outputs=("Y101",)),
    ]
    ready.sim._layout_reader = lambda _path, used: build_panel_layout(modules, used)
    win = simulator(ready)
    texts = {
        win._canvas.itemcget(item, "text")
        for item in win._canvas.find_all()
        if win._canvas.type(item) == "text"
    }
    assert {"CPU", "Option slot 0", "Expansion 1"} <= texts
    assert "Built-in I/O" not in texts, "a CPU without I/O is just the slim card"

    slot_x = MARGIN + CPU_CARD_W + HOUSING_GAP
    assert win._inputs["X001"]["x"] == slot_x
    assert win._outputs["Y101"]["x"] == slot_x + win._card_w + CARD_GAP


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
    assert c.itemcget(bench["pill"], "fill") == P.LINK_BENCH_BG
    assert c.itemcget(bench["pill"], "outline") == P.LINK_BENCH
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
        # A bit enable is ON or OFF: OFF drives the link while Y001 is off.
        assert dialog._when_bit.winfo_manager() and not dialog._when_word.winfo_manager()
        dialog._when_on.set(False)
        assert dialog.build() == BenchLink("Y001", 0, on_delay="2s")
        # A word enable matches a value instead.
        dialog._enable_var.set("ds1")
        assert dialog._when_word.winfo_manager() and not dialog._when_bit.winfo_manager()
        dialog._trigger_var.set("2")
        dialog._kind_var.set("pulse")
        dialog._on_kind_changed()
        assert dialog.build() == BenchLink("DS1", 2, profile="pulse:on_dwell=500ms|off_dwell=500ms")
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


def test_dragging_an_output_onto_an_input_opens_the_link_dialog(simulator, ready, monkeypatch):
    win = simulator(ready)
    opened: list = []
    monkeypatch.setattr(
        win, "_open_link_dialog", lambda address, **kw: opened.append((address, kw))
    )
    target = win._inputs["X002"]

    win._start_link_drag("Y001")
    win._on_link_drag(SimpleNamespace(x=target["x"] + 100, y=target["cy"]))
    assert win._link_drag["target"] == "in:X002"
    assert win._canvas.find_withtag("drag")

    win._on_any_release(None)
    assert opened == [("X002", {"analog": False, "enable": "Y001"})]
    assert not win._canvas.find_withtag("drag")


def test_a_drag_released_off_an_input_does_nothing(simulator, ready, monkeypatch):
    win = simulator(ready)
    opened: list = []
    monkeypatch.setattr(win, "_open_link_dialog", lambda address, **kw: opened.append(address))
    win._start_link_drag("Y001")
    win._on_link_drag(SimpleNamespace(x=2, y=2))
    win._on_any_release(None)
    assert opened == []


# ----------------------------------------------------------------------
# Questions in the console, echo, countdowns
# ----------------------------------------------------------------------


def _labels_of(menu) -> list[str]:
    end = menu.index("end")
    return [
        menu.entrycget(i, "label")
        for i in range(0 if end is None else end + 1)
        if menu.type(i) not in ("separator", "tearoff")
    ]


def _popup_menu(win, monkeypatch, open_menu):
    """The menu *open_menu* builds, captured instead of posted."""
    shown = []
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, *_a: shown.append(self))
    open_menu()
    return shown[-1]


def test_output_menu_asks_the_console_why(simulator, ready, monkeypatch):
    win = simulator(ready)
    event = SimpleNamespace(x_root=0, y_root=0)
    menu = _popup_menu(win, monkeypatch, lambda: win._output_menu(event, "Y001"))
    labels = _labels_of(menu)
    assert labels[:3] == ["Why?", "Show simplified logic", "How (experimental)"]

    win._toggle_console()  # hidden: asking shows it again
    menu.invoke(0)
    assert win._console_shown()
    assert ">>> why Y001" in _output(win._console)
    assert win._console_history[-1] == "why Y001"

    # One command at a time: while it runs, the questions are greyed out.
    menu = _popup_menu(win, monkeypatch, lambda: win._input_menu(event, "X001"))
    assert str(menu.entrycget(0, "state")) == "disabled"


def test_how_to_turn_off_negates_the_tag(simulator, ready, monkeypatch):
    win = simulator(ready)
    event = SimpleNamespace(x_root=0, y_root=0)
    menu = _popup_menu(win, monkeypatch, lambda: win._output_menu(event, "Y001"))
    how = menu.nametowidget(menu.entrycget(2, "menu"))
    how.invoke(1)
    assert ">>> how ~Y001" in _output(win._console)


def test_panel_actions_echo_into_the_console(simulator, ready):
    win = simulator(ready)
    ready.sim.toggle_switch("X001")
    assert "# patch X001 true" in _output(win._console)
    ranges = win._console._output.tag_ranges("echo")
    assert ranges, "echo lines are styled apart from command output"


def test_link_chip_counts_down_while_the_delay_runs(simulator, ready):
    from clicknick.services.sim_state import BenchLink

    win = simulator(ready)
    ready.sim.link("X002", BenchLink("Y001", on_delay="2s"))
    _frame(ready)
    win._refresh_dynamic()
    info = win._inputs["X002"]
    assert win._canvas.itemcget(info["pill_text"], "text") == "Y001"

    ready.dap.frame(links_pending={"X002": 1240})
    ready.scheduler.run_ready()
    win._refresh_dynamic()
    assert win._canvas.itemcget(info["pill_text"], "text") == "1.2s"
    assert win._canvas.itemcget(info["pending"], "state") == "normal"


def test_hovering_a_wiring_entry_draws_its_wire(simulator, ready):
    from clicknick.services.sim_state import BenchLink

    win = simulator(ready)
    ready.sim.link("X002", BenchLink("Y001", on_delay="2s"))
    _frame(ready)
    win._populate_wiring_menu()
    [index] = list(win._wiring_entries)
    win._wiring_menu.activate(index)
    win._on_wiring_select()
    assert win._canvas.find_withtag("wire")
    win._wiring_menu.activate("none")
    win._on_wiring_select()
    assert not win._canvas.find_withtag("wire")
