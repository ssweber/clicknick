"""Check that the simulator hardware panel shows module cards and placeholders for used I/O."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.services.sim_hardware import (
    build_panel_layout,
    io_addresses,
    read_panel_layout,
)


def _module(location, position, model, inputs=(), outputs=(), ai=(), ao=()):
    return SimpleNamespace(
        location=location,
        position=position,
        module=SimpleNamespace(model=model),
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        analog_inputs=tuple(ai),
        analog_outputs=tuple(ao),
    )


CPU = _module(
    "cpu",
    0,
    "C0-02DD1-D",
    inputs=("X001", "X002", "X003", "X004"),
    outputs=("Y001", "Y002"),
    ai=("DF1", None),
    ao=("DF5",),
)
EXPANSION = _module("expansion", 1, "C0-08ND3", inputs=[f"X10{i}" for i in range(1, 9)])


def test_cards_follow_physical_order_with_terminals_by_kind():
    layout = build_panel_layout([CPU, EXPANSION])

    assert [card.key for card in layout.cards] == ["cpu", "expansion1"]
    assert [card.title for card in layout.cards] == ["CPU", "Expansion 1"]
    cpu = layout.cards[0]
    assert [t.address for t in cpu.of_kind("input")] == ["X001", "X002", "X003", "X004"]
    assert [(t.channel, t.address) for t in cpu.of_kind("analog_in")] == [(1, "DF1"), (2, None)]
    assert layout.has_cpu
    assert layout.modules == ("cpu:C0-02DD1-D", "expansion1:C0-08ND3")


def _placeholders(layout):
    return [c for c in layout.cards if not c.installed]


def _addresses(card, kind):
    return [t.address for t in card.of_kind(kind)]


def test_used_io_without_a_module_gets_a_placeholder_at_its_position():
    layout = build_panel_layout([CPU], used_io={"X001", "X201", "Y301", "X021", "Y002"})

    assert [(c.key, c.installed) for c in layout.cards] == [
        ("cpu", True),
        ("slot1", False),
        ("expansion2", False),
        ("expansion3", False),
    ]
    slot, exp2, exp3 = _placeholders(layout)
    assert slot.title == "Option slot 1 - unassigned"
    assert _addresses(slot, "input") == ["X021"]
    assert _addresses(exp2, "input") == ["X201"]
    assert _addresses(exp3, "output") == ["Y301"]
    assert "X201" in layout.addresses("input")
    assert "Y301" in layout.addresses("output")


def test_x_and_y_of_one_position_share_one_placeholder():
    layout = build_panel_layout(
        [CPU],
        used_io={f"X10{i}" for i in range(1, 9)} | {f"Y10{i}" for i in range(1, 9)},
    )

    (combo,) = _placeholders(layout)
    assert combo.key == "expansion1"
    assert combo.title == "Expansion 1 - unassigned"
    assert _addresses(combo, "input") == [f"X10{i}" for i in range(1, 9)]
    assert _addresses(combo, "output") == [f"Y10{i}" for i in range(1, 9)]
    assert layout.modules == ("cpu:C0-02DD1-D",)


def test_placeholder_sits_between_the_real_cards_around_it():
    third = _module("expansion", 3, "C0-08ND3", inputs=[f"X30{i}" for i in range(1, 9)])
    layout = build_panel_layout([CPU, EXPANSION, third], used_io={"X201"})

    assert [(c.key, c.installed) for c in layout.cards] == [
        ("cpu", True),
        ("expansion1", True),
        ("expansion2", False),
        ("expansion3", True),
    ]
    assert layout.modules == ("cpu:C0-02DD1-D", "expansion1:C0-08ND3", "expansion3:C0-08ND3")


def test_io_beyond_a_modules_points_goes_on_a_placeholder_after_it():
    layout = build_panel_layout([CPU, EXPANSION], used_io={"X112", "Y101", "X005"})

    assert [(c.key, c.installed) for c in layout.cards] == [
        ("cpu", True),
        ("cpu", False),
        ("expansion1", True),
        ("expansion1", False),
    ]
    cpu_extra, exp_extra = _placeholders(layout)
    assert _addresses(cpu_extra, "input") == ["X005"]
    assert _addresses(exp_extra, "input") == ["X112"]
    assert _addresses(exp_extra, "output") == ["Y101"]
    assert layout.modules == ("cpu:C0-02DD1-D", "expansion1:C0-08ND3")


def test_poll_addresses_cover_every_terminal_once():
    layout = build_panel_layout([CPU], used_io={"X201"})
    polled = layout.poll_addresses
    assert len(polled) == len(set(polled))
    assert set(polled) == {"X001", "X002", "X003", "X004", "Y001", "Y002", "DF1", "DF5", "X201"}


def test_no_cpu_layout():
    layout = build_panel_layout([], used_io={"X001"})
    assert not layout.has_cpu
    assert [(c.key, c.installed) for c in layout.cards] == [("cpu", False)]
    assert layout.cards[0].title == "CPU - unassigned"
    assert layout.modules == ()


def test_io_addresses_keeps_only_x_and_y():
    keys = [get_addr_key("X", 1), get_addr_key("Y", 101), get_addr_key("DS", 1)]
    assert io_addresses(keys) == {"X001", "Y101"}


def test_reads_a_real_project_ini(tmp_path):
    import pyclickplc

    if not hasattr(pyclickplc, "read_io_layout"):
        pytest.skip("installed pyclickplc predates read_io_layout")
    ini = tmp_path / "Project.ini"
    ini.write_text(
        "[SystemConfig]\nItem1=192\n[CPUBuild]\nAD1=DF1,10,0\nDA1=DF5,10,0\n", encoding="utf-8"
    )

    layout = read_panel_layout(ini, used_io={"X501"})

    assert layout.has_cpu
    cpu = layout.cards[0]
    assert cpu.location == "cpu"
    assert cpu.of_kind("input")[0].address == "X001"
    assert _addresses(_placeholders(layout)[0], "input") == ["X501"]


def test_an_unknown_module_is_named_in_the_panel_text(tmp_path):
    from clicknick.services.sim_hardware import unknown_layout_text

    ini = tmp_path / "Project.ini"
    # -1 is not a CLICK module ID, so pyclickplc's catalog never has it.
    ini.write_text("[SystemConfig]\nItem1=196\nItem10=-1\n", encoding="utf-8")
    layout = read_panel_layout(ini)
    text = unknown_layout_text(layout)

    assert text is not None
    assert "Option slot 0 (module ID -1)" in text
    assert "still runs the program" in text
    assert "The hardware panel shows the modules that ClickNick knows" in text
    assert "No CPU" not in text
    assert "option slot, because" not in text
    assert layout.has_cpu
    assert [card.key for card in layout.cards] == ["cpu"]


def test_an_unknown_cpu_says_that_clicknick_reads_no_option_slot():
    from pyclickplc import UnknownModule

    from clicknick.services.sim_hardware import unknown_layout_text

    unknown = (UnknownModule("cpu", 0, 999), UnknownModule("expansion", 2, -1))
    text = unknown_layout_text(build_panel_layout([EXPANSION], unknown=unknown))

    assert text is not None
    assert "lists modules that ClickNick does not know: CPU (module ID 999) and " in text
    assert "Expansion 2 (module ID -1)." in text
    assert "ClickNick reads no option slot, because the CPU sets how many there are." in text


def test_a_layout_with_only_known_modules_has_no_unknown_text():
    from clicknick.services.sim_hardware import unknown_layout_text

    assert unknown_layout_text(build_panel_layout([CPU, EXPANSION])) is None


def test_a_read_error_that_is_not_a_value_error_does_not_say_the_simulator_runs():
    from clicknick.services.sim_hardware import layout_error_text

    text = layout_error_text(PermissionError("locked"))

    assert "locked" in text
    assert "still runs" not in text


RECORDED_LAYOUTS = Path(__file__).resolve().parents[1] / "devtools" / "click_smoke_layouts.json"


def _recorded_cards(model):
    """Return the installed cards that CLICK 4.00 was observed to give a new project of *model*."""
    layouts = json.loads(RECORDED_LAYOUTS.read_text(encoding="utf-8"))
    return [(c["location"], c["position"], c["model"]) for c in layouts[model]["cards"]]


def _plus_layout(tmp_path, cpu_id, slots, used_io):
    """Read a Project.ini with the CPU *cpu_id* and the module IDs *slots* in option slots 0 and 1."""
    lines = ["[SystemConfig]", f"Item1={cpu_id}"]
    lines += [f"Item{10 + position}={module_id}" for position, module_id in enumerate(slots)]
    ini = tmp_path / "Project.ini"
    ini.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return read_panel_layout(ini, used_io=used_io)


def _installed(layout):
    return [(c.location, c.position, c.model) for c in layout.cards if c.installed]


def test_a_click_plus_puts_x001_to_x016_on_option_slot_0(tmp_path):
    # 198 is C2-03CPU. CLICK 4.00 fills an empty option slot with C2-FILL, module 8192.
    layout = _plus_layout(tmp_path, 198, [8192], used_io={"X001", "Y016"})

    assert _installed(layout) == _recorded_cards("C2-03CPU")
    assert [(c.key, c.installed) for c in layout.cards] == [
        ("cpu", True),
        ("slot0", True),
        ("slot0", False),
    ]
    (placeholder,) = _placeholders(layout)
    assert placeholder.title == "Option slot 0 - unassigned"
    assert _addresses(placeholder, "input") == ["X001"]
    assert _addresses(placeholder, "output") == ["Y016"]


def test_a_click_plus_with_two_slots_puts_each_placeholder_after_its_slot(tmp_path):
    # 201 is C2-03CPU-2, with option slots 0 and 1.
    layout = _plus_layout(tmp_path, 201, [8192, 8192], used_io={"X001", "X021"})

    assert _installed(layout) == _recorded_cards("C2-03CPU-2")
    assert [(c.key, c.installed) for c in layout.cards] == [
        ("cpu", True),
        ("slot0", True),
        ("slot0", False),
        ("slot1", True),
        ("slot1", False),
    ]
    slot0, slot1 = _placeholders(layout)
    assert _addresses(slot0, "input") == ["X001"]
    assert _addresses(slot1, "input") == ["X021"]


def test_io_beyond_the_points_of_a_click_plus_slot_module_goes_after_that_module(tmp_path):
    # 8193 is C2-14D1, with 8 inputs and 6 outputs.
    layout = _plus_layout(tmp_path, 198, [8193], used_io={"X003", "X012", "Y007"})

    assert [(c.key, c.installed) for c in layout.cards] == [
        ("cpu", True),
        ("slot0", True),
        ("slot0", False),
    ]
    (placeholder,) = _placeholders(layout)
    assert _addresses(placeholder, "input") == ["X012"]
    assert _addresses(placeholder, "output") == ["Y007"]


def test_a_click_plus_with_no_module_listed_in_slot_0_still_names_slot_0(tmp_path):
    layout = _plus_layout(tmp_path, 198, [], used_io={"X001"})

    assert [(c.key, c.installed) for c in layout.cards] == [("cpu", True), ("slot0", False)]


def test_a_c0_cpu_keeps_its_extra_io_on_a_placeholder_right_after_it():
    layout = build_panel_layout([CPU, EXPANSION], used_io={"X005", "X021", "X201"})

    assert [(c.key, c.installed) for c in layout.cards] == [
        ("cpu", True),
        ("cpu", False),
        ("slot1", False),
        ("expansion1", True),
        ("expansion2", False),
    ]
    cpu_extra = _placeholders(layout)[0]
    assert cpu_extra.title == "CPU - unassigned"
    assert _addresses(cpu_extra, "input") == ["X005"]


def test_with_no_cpu_the_placeholders_follow_address_order():
    layout = build_panel_layout([], used_io={"X001", "X021", "X101"})

    assert [(c.key, c.installed) for c in layout.cards] == [
        ("cpu", False),
        ("slot1", False),
        ("expansion1", False),
    ]


def test_an_empty_option_slot_shows_as_a_card_with_no_terminals(tmp_path):
    # CLICK 4.00 saves a CLICK PLUS option slot that holds no module as module 8192 (C2-FILL).
    ini = tmp_path / "Project.ini"
    ini.write_text("[SystemConfig]\nItem1=199\nItem10=8192\n", encoding="utf-8")

    layout = read_panel_layout(ini, used_io=set())

    slot = next(card for card in layout.cards if card.location == "slot")
    assert slot.model == "C2-FILL"
    assert slot.terminals == ()
