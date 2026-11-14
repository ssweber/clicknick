"""Simulator hardware panel: cards from the module list and placeholders for used I/O."""

from __future__ import annotations

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
