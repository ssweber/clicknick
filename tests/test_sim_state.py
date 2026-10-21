"""Simulator settings: file format, where the file lives, and restoring onto new hardware."""

from __future__ import annotations

from clicknick.services.sim_state import (
    BenchLink,
    SimulatorState,
    adopt_snapshot,
    app_data_state_path,
    dump_state,
    load_state,
    restore_state,
    save_state,
    settle_state_file,
)


def _state() -> SimulatorState:
    return SimulatorState(
        switches={"X001": True, "X102": False},
        momentary=frozenset({"X002"}),
        analog={"DF1": 4.5},
        forces={"Y001": True, "DS10": 7, "TXT1": "A"},
        links={
            "X002": BenchLink("Y001", on_delay="2s", off_delay="500ms"),
            "X003": BenchLink(None, enabled=False),
            "DF1": BenchLink("Y002", profile="ramp:up=0.8|down=-0.05"),
            "X004": BenchLink("DS1", trigger=2, on_delay="1s"),
        },
        bench_wiring=False,
        run_hint_seen=True,
        modbus_port=5020,
        modules=("cpu:C2-03CPU", "expansion1:C2-16DR"),
    )


def test_round_trip(tmp_path):
    path = tmp_path / "sim" / "state.toml"
    save_state(path, _state())
    assert load_state(path) == _state()


def test_missing_file_is_an_empty_state(tmp_path):
    assert load_state(tmp_path / "nope.toml") == SimulatorState()


def test_malformed_entries_are_skipped(tmp_path):
    path = tmp_path / "state.toml"
    path.write_text(
        "modbus_port = 99999\nrun_hint_seen = 'yes'\n"
        "[switches]\nx1 = true\nnot_an_address = true\nX003 = 1\n"
        "[analog]\nDF2 = true\nDF3 = 2\n"
        "[input_modes]\nX004 = 'momentary'\nX005 = 'other'\n",
        encoding="utf-8",
    )
    state = load_state(path)
    assert state.switches == {"X001": True}
    assert state.analog == {"DF3": 2.0}
    assert state.momentary == frozenset({"X004"})
    assert state.modbus_port == 502
    assert state.run_hint_seen is False


def test_dump_sorts_addresses_in_address_order():
    text = dump_state(SimulatorState(switches={"X101": True, "X002": True, "X010": True}))
    assert text.index("X002") < text.index("X010") < text.index("X101")


def test_without_workspace_state_lives_in_app_data(tmp_path):
    located = settle_state_file("Line 1", None, app_data_root=tmp_path)
    assert located.path == app_data_state_path("Line 1", root=tmp_path)
    assert located.notice is None


def test_unsafe_plc_name_is_a_safe_file_name(tmp_path):
    assert app_data_state_path('a/b:c*"', root=tmp_path).name == "a_b_c__.toml"


def test_pairing_a_workspace_moves_the_app_data_file(tmp_path):
    app_root = tmp_path / "app"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    save_state(app_data_state_path("PLC", root=app_root), _state())

    located = settle_state_file("PLC", workspace, app_data_root=app_root)

    assert located.path == workspace / "simulator.toml"
    assert located.notice is None
    assert load_state(located.path) == _state()
    assert not app_data_state_path("PLC", root=app_root).exists()


def test_existing_workspace_file_wins_and_user_is_told(tmp_path):
    app_root = tmp_path / "app"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    save_state(app_data_state_path("PLC", root=app_root), _state())
    theirs = SimulatorState(switches={"X009": True})
    save_state(workspace / "simulator.toml", theirs)

    located = settle_state_file("PLC", workspace, app_data_root=app_root)

    assert located.path == workspace / "simulator.toml"
    assert located.notice and "already had simulator settings" in located.notice
    assert load_state(located.path) == theirs
    assert not app_data_state_path("PLC", root=app_root).exists()


def test_restore_keeps_only_addresses_the_hardware_provides():
    result = restore_state(
        _state(),
        inputs=["X001", "X002"],
        analog_inputs=[],
        modules=("cpu:C2-03CPU",),
    )
    assert result.state.switches == {"X001": True}
    assert result.state.momentary == frozenset({"X002"})
    assert result.state.analog == {}
    # Forces may target any address, so they all survive.
    assert result.state.forces == _state().forces
    assert result.dropped == ("X102", "DF1")
    assert result.hardware_changed is True
    assert result.state.modules == ("cpu:C2-03CPU",)


def test_restore_on_unchanged_hardware_drops_nothing():
    state = _state()
    result = restore_state(
        state, inputs=["X001", "X002", "X102"], analog_inputs=["DF1"], modules=state.modules
    )
    assert result.dropped == ()
    assert result.hardware_changed is False
    assert result.state == state


def test_snapshot_wins_for_maintained_inputs_and_analog_values():
    state = SimulatorState(
        switches={"X001": True, "X009": True}, momentary=frozenset({"X002"}), forces={"Y1": 1}
    )
    adopted = adopt_snapshot(
        state,
        {"X001": False, "X002": True, "X003": True, "DF1": 2, "DF2": True},
        inputs=["X001", "X002", "X003"],
        analog_inputs=["DF1", "DF2"],
    )
    assert adopted.switches == {"X003": True, "X009": True}
    assert adopted.analog == {"DF1": 2.0}
    assert adopted.forces == state.forces


def test_malformed_links_are_skipped(tmp_path):
    path = tmp_path / "state.toml"
    path.write_text(
        "[links]\n"
        "x2 = {enable = 'y1', on_delay = '2s'}\n"
        "X003 = {enable = 'nowhere', on_delay = '2s'}\n"
        "X004 = {enable = 'Y001'}\n"
        "X005 = 'Y001'\n"
        "X006 = {cut = true}\n",
        encoding="utf-8",
    )
    assert load_state(path).links == {
        "X002": BenchLink("Y001", on_delay="2s"),
        "X006": BenchLink(None),
    }
