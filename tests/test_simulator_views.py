"""The Console, Simulator window and Dataview panel as observers of one SimulationSession."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pyclickplc.addresses import get_addr_key

tk = pytest.importorskip("tkinter")

from test_simulation_session import Harness, _ready_analysis  # noqa: E402

from clicknick.services.analysis_service import AnalysisService  # noqa: E402
from clicknick.services.physical_response import response  # noqa: E402
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
    started: list = []
    ready.sim._run_background = lambda target, _name: started.append(target)
    win._console._send = lambda command, **_kw: (True, "")
    win._console._submit_command_text("run 10s")
    assert str(win._console._pop_btn.cget("state")) == "disabled"
    win._pop_out_console()
    assert win._console_window is None and win._console_shown()
    started.pop()()
    ready.scheduler.run_ready()
    assert str(win._console._pop_btn.cget("state")) == "normal"


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


def test_unassigned_io_is_drawn_in_its_position_between_real_cards(simulator, ready):
    from clicknick.services.sim_hardware import build_panel_layout
    from clicknick.views.simulator_window import CARD_GAP

    def module(location, position, model, inputs=()):
        return SimpleNamespace(
            location=location, position=position, module=SimpleNamespace(model=model),
            inputs=inputs, outputs=(), analog_inputs=(), analog_outputs=(),
        )  # fmt: skip

    modules = [
        module("cpu", 0, "C2-03CPU-2"),
        module("expansion", 1, "C0-08ND3", inputs=("X101",)),
        module("expansion", 3, "C0-08ND3", inputs=("X301",)),
    ]
    used = {"X201", "Y201"}
    ready.sim._layout_reader = lambda _path, _used: build_panel_layout(modules, used)
    win = simulator(ready)
    texts = {
        win._canvas.itemcget(item, "text")
        for item in win._canvas.find_all()
        if win._canvas.type(item) == "text"
    }
    assert "Expansion 2 - unassigned" in texts
    assert win._inputs["X201"]["x"] == win._inputs["X101"]["x"] + win._card_w + CARD_GAP
    assert win._inputs["X301"]["x"] == win._inputs["X201"]["x"] + win._card_w + CARD_GAP
    assert "Y201" in win._outputs


def _unassigned_module(location, position, model, inputs=()):
    return SimpleNamespace(
        location=location, position=position, module=SimpleNamespace(model=model),
        inputs=inputs, outputs=(), analog_inputs=(), analog_outputs=(),
    )  # fmt: skip


def _texts(win):
    return {
        win._canvas.itemcget(item, "text")
        for item in win._canvas.find_all()
        if win._canvas.type(item) == "text"
    }


def test_option_slot_placeholder_joins_the_housing_and_its_switch_drives_the_input(
    simulator, ready
):
    from clicknick.services.sim_hardware import build_panel_layout
    from clicknick.views.simulator_window import CPU_CARD_W, HOUSING_GAP, MARGIN

    modules = [
        _unassigned_module("cpu", 0, "C2-03CPU-2"),
        _unassigned_module("slot", 0, "C2-08ND3", inputs=("X001", "X002")),
    ]
    ready.sim._layout_reader = lambda _path, used: build_panel_layout(modules, {"X021", "Y021"})
    win = simulator(ready)

    assert "Option slot 1 - unassigned" in _texts(win)
    slot0_x = MARGIN + CPU_CARD_W + HOUSING_GAP
    assert win._inputs["X021"]["x"] == slot0_x + win._card_w + HOUSING_GAP
    win._on_switch_press("X021")
    assert ready.sim.switch_on("X021")
    assert ready.dap.calls[-1] == ("patch", {"X021": True})


def test_placeholder_subtitle_fits_a_card(simulator, ready):
    from clicknick.services.sim_hardware import build_panel_layout

    ready.sim._layout_reader = lambda _path, _used: build_panel_layout(
        [_unassigned_module("cpu", 0, "C2-03CPU-2")], {"X201"}
    )
    win = simulator(ready)
    assert "Used, no module configured" in _texts(win)
    assert win._small.measure("Used, no module configured") <= win._card_w - 20


def test_cpu_placeholder_follows_the_housing_and_a_full_rack_of_them_fits(simulator, ready):
    from clicknick.services.sim_hardware import build_panel_layout
    from clicknick.views.simulator_window import CARD_GAP, CPU_CARD_W, HOUSING_GAP, MARGIN

    modules = [
        _unassigned_module("cpu", 0, "C2-03CPU-2", inputs=("X001", "X002")),
        _unassigned_module("slot", 0, "C2-08ND3", inputs=("X003",)),
    ]
    used = {"X005", "X021"} | {f"X{n}01" for n in range(1, 9)} | {f"Y{n}01" for n in range(1, 9)}
    ready.sim._layout_reader = lambda _path, _used: build_panel_layout(modules, used)
    win = simulator(ready)

    assert {"CPU - unassigned", "Option slot 1 - unassigned", "Expansion 8 - unassigned"} <= _texts(
        win
    )
    cpu_io_x = MARGIN + CPU_CARD_W + HOUSING_GAP
    slot0_x = cpu_io_x + win._card_w + HOUSING_GAP
    slot1_x = slot0_x + win._card_w + HOUSING_GAP
    assert win._inputs["X021"]["x"] == slot1_x
    assert win._inputs["X005"]["x"] == slot1_x + win._card_w + CARD_GAP  # after the housing
    assert all(a in win._inputs for a in used if a.startswith("X"))
    assert all(a in win._outputs for a in used if a.startswith("Y"))
    assert sum(win._drawn_rows) == len(win._drawn_pieces)
    assert float(win._canvas.cget("scrollregion").split()[2]) <= win._requested_width


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

    ready.sim.link("X002", BenchLink("Y001", response=response(on_delay="1s")))
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
    assert win._link_text("X002").startswith("Bench link: driven by Y001 (on_delay=1s).")
    assert win._link_text("X003").startswith("Program link: driven by Y001 (on_delay=1s).")

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
    ready.sim.link("X002", BenchLink("Y001", response=response(on_delay="1s")))
    win = simulator(ready, store)

    win._save_link_to_project("X002")
    assert store.edits == [(aux, "comment", "[link=Motor, on_delay=1s] Aux contact")]
    assert "Saved the link on X002 to the project" in str(win._banner_key)
    assert win._saved_to_project("X002", ready.sim.bench_links["X002"])


def test_save_link_needs_a_nickname(simulator, ready, monkeypatch):
    from clicknick.services.sim_state import BenchLink

    store = _Store({get_addr_key("X", 2): SimpleNamespace(nickname="", comment="")})
    ready.sim.link("X002", BenchLink("Y001", response=response(on_delay="1s")))
    win = simulator(ready, store)
    errors: list[str] = []
    monkeypatch.setattr(win, "_show_action_error", errors.append)
    win._save_link_to_project("X002")
    assert store.edits == []
    assert errors and "nickname first" in errors[0]


def test_wiring_menu_lists_links_and_turns_bench_wiring_off(simulator, ready):
    from clicknick.services.sim_state import BenchLink

    ready.sim.link("X002", BenchLink("Y001", response=response(on_delay="1s")))
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

    ready.sim.link("X002", BenchLink("Y001", response=response(on_delay="1s")))
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
        dialog._key_vars["on_delay"].set("2s")
        dialog._key_vars["off_delay"].set("")
        assert dialog.build() == BenchLink("Y001", response=response(on_delay="2s"))
        # A bit enable is a contact beside the driver: [O] by default, [/] drives
        # the link while Y001 is off.
        assert dialog._when_bit.winfo_manager() and not dialog._when_word.winfo_manager()
        assert dialog._when_bit.grid_info()["row"] == 0
        assert dialog._when_on.get()
        dialog._when_on.set(False)
        assert dialog.build() == BenchLink("Y001", 0, response(on_delay="2s"))
        # A word enable matches a value instead.
        dialog._enable_var.set("ds1")
        assert dialog._when_word.winfo_manager() and not dialog._when_bit.winfo_manager()
        dialog._trigger_var.set("2")
        dialog._kind_var.set("flasher")
        dialog._on_kind_changed()
        assert dialog.build() == BenchLink(
            "DS1", 2, response(flasher_on="500ms", flasher_off="500ms")
        )
        dialog._enable_var.set("nowhere")
        with pytest.raises(ValueError, match="CLICK address"):
            dialog.build()
    finally:
        dialog.destroy()

    dialog = LinkDialog(
        tk_root, feedback="DF1", analog=True,
        current=BenchLink("Y002", response=response(ramp_on="2.0", ramp_off="-1.0")),
        enables=[], on_ok=linked.append,
    )  # fmt: skip
    try:
        assert dialog._kind_var.get() == "ramp"
        assert dialog._key_vars["ramp_on"].get() == "2.0"
        assert dialog._key_vars["ramp_off"].get() == "-1.0"
        dialog._accept()
        assert linked == [BenchLink("Y002", response=response(ramp_on="2.0", ramp_off="-1.0"))]
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_link_dialog_offers_pyrungs_kinds_for_the_input(tk_root):
    from pyrung.core import PHYSICAL_KINDS

    from clicknick.views.sim_link_dialog import LinkDialog

    for analog in (False, True):
        dialog = LinkDialog(
            tk_root, feedback="X001", analog=analog, current=None, enables=[],
            on_ok=lambda _link: None,
        )  # fmt: skip
        try:
            expected = [
                k.name for k in PHYSICAL_KINDS if k.feedback == ("analog" if analog else "bool")
            ]
            assert [k.name for k in dialog._kinds] == expected
            assert dialog._kind_var.get() == expected[0]
        finally:
            dialog.destroy()


def test_link_dialog_shows_each_kinds_fields_and_checks_them(tk_root):
    from clicknick.services.sim_state import BenchLink
    from clicknick.views.sim_link_dialog import LinkDialog

    dialog = LinkDialog(
        tk_root, feedback="X002", analog=False, current=None, enables=[], on_ok=lambda _l: None,
        enable="Y001",
    )  # fmt: skip
    try:

        def shown() -> list[str]:
            return [
                str(widget.cget("text"))
                for widget in dialog._field_widgets
                if int(widget.grid_info()["column"]) == 0
            ]

        assert shown() == ["On delay", "Off delay"]
        # A missing pair is named by its labels, and a value goes through pyrung's parser.
        dialog._key_vars["on_delay"].set("")
        dialog._key_vars["off_delay"].set("")
        with pytest.raises(ValueError, match="Enter on delay or off delay."):
            dialog.build()
        dialog._key_vars["on_delay"].set("2")
        with pytest.raises(ValueError, match="^On delay: no duration tokens"):
            dialog.build()

        # Timed has a time and a Maintained checkbox.
        dialog._kind_var.set("timed")
        dialog._on_kind_changed()
        assert shown() == ["On time", "Maintained"]
        assert dialog.build() == BenchLink("Y001", None, response(timed="200ms"))
        dialog._key_vars["maintained"].set(True)
        assert dialog.build() == BenchLink("Y001", None, response(timed="200ms", maintained=True))
        dialog._key_vars["timed"].set("")
        with pytest.raises(ValueError, match="Enter on time."):
            dialog.build()

        # Toggle has no field: picking it is the whole response.
        dialog._kind_var.set("toggle")
        dialog._on_kind_changed()
        assert shown() == []
        assert dialog.build() == BenchLink("Y001", None, response(toggle=True))

        # Each key keeps the value typed into it across kinds.
        dialog._kind_var.set("delay")
        dialog._on_kind_changed()
        assert dialog._key_vars["on_delay"].get() == "2"
    finally:
        dialog.destroy()


def test_link_dialog_analog_rates_must_be_numbers(tk_root):
    from clicknick.services.sim_state import BenchLink
    from clicknick.views.sim_link_dialog import LinkDialog

    dialog = LinkDialog(
        tk_root, feedback="DF1", analog=True, current=None, enables=[], on_ok=lambda _l: None,
        enable="Y001",
    )  # fmt: skip
    try:
        dialog._key_vars["ramp_on"].set("fast")
        with pytest.raises(ValueError, match="^Rate on: expected a number"):
            dialog.build()
        # Rate off may be left out: pyrung holds the value.
        dialog._key_vars["ramp_on"].set("0.8")
        dialog._key_vars["ramp_off"].set("")
        assert dialog.build() == BenchLink("Y001", None, response(ramp_on="0.8"))
        # Approach takes a tag name as its target.
        dialog._kind_var.set("approach")
        dialog._on_kind_changed()
        dialog._key_vars["approach_to"].set("Oven_SP")
        assert dialog.build() == BenchLink(
            "Y001", None, response(approach_to="Oven_SP", approach_rate="0.3")
        )
    finally:
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
    ready.sim.link("X002", BenchLink("Y001", response=response(on_delay="2s")))
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
    ready.sim.link("X002", BenchLink("Y001", response=response(on_delay="2s")))
    _frame(ready)
    win._populate_wiring_menu()
    [index] = list(win._wiring_entries)
    win._wiring_menu.activate(index)
    win._on_wiring_select()
    assert win._canvas.find_withtag("wire")
    win._wiring_menu.activate("none")
    win._on_wiring_select()
    assert not win._canvas.find_withtag("wire")


def test_toggling_the_console_brings_it_back_at_its_height(simulator, ready):
    win = simulator(ready)
    win.geometry("1100x760")
    win.update()
    paned = win._paned
    opened = paned.sashpos(0)

    for _ in range(2):  # not a sliver at the bottom, and not shrinking each time
        win._toggle_console()
        win.update()
        win._toggle_console()
        win.update()
        assert abs(paned.sashpos(0) - opened) <= 2

    paned.sashpos(0, opened - 100)  # dragged taller
    win.update()
    win._toggle_console()
    win.update()
    win._toggle_console()
    win.update()
    assert abs(paned.sashpos(0) - (opened - 100)) <= 2


def test_clicking_the_padlock_releases_the_force(simulator, ready):
    win = simulator(ready)
    win.geometry("1100x760")
    ready.sim.force("Y001", True)
    win._refresh_dynamic()
    win.update()
    c = win._canvas
    x0, y0, x1, y1 = c.bbox("badge:Y001")
    x, y = (x0 + x1) // 2, (y0 + y1) // 2
    c.event_generate("<Motion>", x=x, y=y)
    c.event_generate("<ButtonPress-1>", x=x, y=y)
    c.event_generate("<ButtonRelease-1>", x=x, y=y)
    win.update()
    assert "Y001" not in ready.sim.forces
    assert win._link_drag is None, "the click is not also the start of a link drag"


def test_labels_offer_a_tooltip_only_for_a_comment(simulator, ready):
    rows = {
        get_addr_key("X", 1): SimpleNamespace(nickname="Start_PB", comment=""),
        get_addr_key("X", 2): SimpleNamespace(nickname="Motor_Aux", comment="Aux contact on M1"),
    }
    store = SimpleNamespace(
        visible_state=rows, add_observer=lambda _cb: None, remove_observer=lambda _cb: None
    )
    win = simulator(ready, store)
    c = win._canvas

    def has_tooltip(text: str) -> bool:
        [item] = [i for i in c.find_all() if c.type(i) == "text" and c.itemcget(i, "text") == text]
        return bool(c.tag_bind(item, "<Enter>"))

    assert not has_tooltip("Start_PB"), "address and nickname are already on screen"
    assert has_tooltip("Motor_Aux")


def test_double_clicking_an_output_forces_it_the_other_way_then_releases(simulator, ready):
    win = simulator(ready)
    assert win._canvas.tag_bind("out:Y001", "<Double-Button-1>"), "on the LED and the name"
    ready.sim._values = {"Y001": False}
    win._flip_output("Y001")
    assert ready.sim.forces == {"Y001": True}
    assert "release" in win._output_hint("Y001")
    win._flip_output("Y001")
    assert ready.sim.forces == {}

    ready.sim._values = {"Y001": True}
    win._flip_output("Y001")
    assert ready.sim.forces == {"Y001": False}


def test_an_analog_input_gets_its_slider_once_the_simulation_gives_its_range(simulator, ready):
    win = simulator(ready)
    assert "scale" not in win._analog_in["DF1"]

    # The simulation's first frame carries the tag hints.
    ready.dap.tag_hints = {"DF1": {"min": 0.0, "max": 100.0, "rangeDefault": False}}
    ready.dap.frame(scan_id=1)
    ready.scheduler.run_ready()

    assert "scale" in win._analog_in["DF1"]


class _ObservedStore:
    def __init__(self, nickname: str) -> None:
        self.visible_state = {get_addr_key("X", 1): SimpleNamespace(nickname=nickname, comment="")}
        self.observers: list = []

    def add_observer(self, callback) -> None:
        self.observers.append(callback)

    def remove_observer(self, callback) -> None:
        self.observers.remove(callback)


def test_the_simulator_follows_the_address_data_the_app_holds_now(tk_root, monkeypatch, ready):
    from clicknick.views.console_panel import ConsolePanel
    from clicknick.views.simulator_window import SimulatorWindow

    monkeypatch.setattr(ConsolePanel, "_start_background", lambda _self, _t, *, name: None)
    first, second = _ObservedStore("Start_PB"), _ObservedStore("Old")
    current = [first]
    win = SimulatorWindow(
        tk_root,
        simulation=ready.sim,
        get_store=lambda: current[0],
        get_analysis=lambda: ready.analysis,
        open_dataview=lambda: None,
    )
    try:
        assert len(first.observers) == 1
        current[0] = second  # a CSV was loaded: the app holds another store
        win.after_cancel(win._tick_after_id)
        win._tick()

        assert first.observers == []
        assert len(second.observers) == 1
        second.visible_state[get_addr_key("X", 1)] = SimpleNamespace(nickname="Renamed", comment="")
        second.observers[0](second, {get_addr_key("X", 1)})
        texts = [
            win._canvas.itemcget(item, "text")
            for item in win._canvas.find_all()
            if win._canvas.type(item) == "text"
        ]
        assert "Renamed" in texts
    finally:
        win._on_close()
    assert second.observers == []


def _rebuilt(harness) -> None:
    from test_simulation_session import _rebuild

    from clicknick.simulation_session import WATCH_MS

    _rebuild(harness)
    harness.scheduler.fire(WATCH_MS)


def test_a_changed_program_is_offered_with_clicks_ways_of_writing_it(simulator, ready):
    win = simulator(ready)
    _rebuilt(ready)
    [labels] = [labels for text, labels in win._banner_key if "CLICK saved" in text]
    assert labels == ("Write",)

    ready.sim.set_switch_position("run")
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()
    [labels] = [labels for text, labels in win._banner_key if "CLICK saved" in text]
    assert labels == ("RUN Time Edit", "Stop and Write")

    [row] = [
        row
        for row in win._banner.winfo_children()
        if "CLICK saved" in str(row.winfo_children()[0].cget("text"))
    ]
    [button] = [
        b
        for b in row.winfo_children()
        if b.winfo_class() == "TButton" and b.cget("text") == "RUN Time Edit"
    ]
    button.invoke()
    ready.scheduler.run_ready()
    assert ("reload",) in ready.dap.calls
    assert not any("CLICK saved" in text for text, _labels in win._banner_key)
    assert len(ready.daps) == 1


def test_restart_starts_the_simulation_over(simulator, ready):
    win = simulator(ready)
    assert str(win._restart_btn.cget("state")) == "normal"
    win._restart_btn.invoke()
    ready.scheduler.run_ready()
    assert len(ready.daps) == 2
    assert ("terminate",) in ready.daps[0].calls

    ready.sim.turn_off()
    win._refresh_toolbar()
    assert str(win._restart_btn.cget("state")) == "disabled"


def test_a_console_reload_writes_the_program_and_autoreload_is_refused(simulator, ready):
    win = simulator(ready)
    _rebuilt(ready)
    sent: list[str] = []
    win._console._send = lambda command, **_kw: (sent.append(command), (True, ""))[1]

    win._console._submit_command_text("autoreload")
    assert "autoreload stays off" in _output(win._console)
    win._console._submit_command_text("reload; continue")
    assert "Send reload on its own." in _output(win._console)
    assert sent == [] and ("reload",) not in ready.dap.calls

    win._console._submit_command_text("reload")
    ready.scheduler.run_ready()
    assert ("reload",) in ready.dap.calls
    assert ready.sim.program_change is None
    assert sent == []


def test_the_console_waits_while_the_program_is_written(simulator, ready):
    from test_simulation_session import _record_unreadable

    win = simulator(ready)
    _rebuilt(ready)
    sent: list[str] = []
    win._console._send = lambda command, **_kw: (sent.append(command), (True, ""))[1]
    jobs: list = []
    ready.sim._run_serial = jobs.append

    win._console._submit_command_text("reload")
    assert ready.sim.writing
    win._refresh_toolbar()
    assert str(win._restart_btn.cget("state")) == "disabled"
    win._console._submit_command_text("force C1 1")
    assert "Send it again once it is written." in _output(win._console)
    assert sent == []

    while jobs:
        jobs.pop(0)()
    ready.scheduler.run_ready()
    assert not ready.sim.writing

    _rebuilt(ready)
    _record_unreadable(ready.analysis.project_dir, 4)
    win._console._submit_command_text("reload")
    assert "Cannot write the program: ClickNick cannot read this rung" in _output(win._console)
    while jobs:
        jobs.pop(0)()
    assert ready.dap.calls.count(("reload",)) == 1


def test_closing_the_simulator_mid_command_does_not_hold_writes_back(simulator, ready):
    win = simulator(ready)
    _rebuilt(ready)
    started: list = []
    ready.sim._run_background = lambda target, _name: started.append(target)
    win._console._send = lambda command, **_kw: (True, f"{command}: done")

    win._console._submit_command_text("run 10s")
    assert win._console.busy
    assert ready.sim.program_change.actions == ()
    win._on_close()  # the command is still in flight

    started.pop()()
    ready.scheduler.run_ready()
    assert ready.sim.program_change.actions == ("write",)

    again = simulator(ready, turn_on=False)
    assert not again._console.busy
    again._console._submit_command_text("reload")
    ready.scheduler.run_ready()
    assert ("reload",) in ready.dap.calls
    assert "while a Console command runs" not in _output(again._console)


def test_a_reopened_console_shows_a_command_still_running_and_stops_it(simulator, ready):
    win = simulator(ready)
    _rebuilt(ready)
    started: list = []
    ready.sim._run_background = lambda target, _name: started.append(target)
    win._console._send = lambda command, **_kw: (True, "")
    win._console._submit_command_text("run 10m")
    win._on_close()

    again = simulator(ready, turn_on=False)
    console = again._console
    assert console.busy and ready.sim.console_busy
    assert console._send_btn.cget("text") == "Stop"
    note = "A Console command is still running; the program can be written once it ends"
    assert note in ready.sim.program_change.text
    assert any(note in text for text, _labels in again._banner_key)

    sent: list[str] = []
    console._send = lambda command, **_kw: (sent.append(command), (True, ""))[1]
    console._start_background = lambda target, *, name: target()
    console._send_btn.invoke()
    assert sent == ["stop"]

    started.pop()()  # pyrung ends the command it was asked to stop
    ready.scheduler.run_ready()
    assert not console.busy
    assert console._send_btn.cget("text") == "Send"
    assert note not in ready.sim.program_change.text
    assert ready.sim.program_change.actions == ("write",)
