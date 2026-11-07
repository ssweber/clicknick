"""ClickNick reads every physical kind and key from pyrung's table."""

from __future__ import annotations

from dataclasses import replace

from pyrung.click.tag_map import TagMeta, format_tag_meta
from pyrung.core.physical import PHYSICAL_KEYS, PHYSICAL_KINDS

from clicknick.services.physical_response import (
    cli_option,
    cli_usage,
    dap_arguments,
    kinds_for,
    meta_fields,
    meta_response,
    response,
    response_check,
    response_from_dap,
    response_kind,
    response_label,
    response_of,
    same_response,
    shown_keys,
)


def test_a_response_keeps_table_order_and_drops_unset_keys():
    values = {"off_delay": "500ms", "on_delay": " 2s ", "link": "Run", "toggle": False}
    assert response_of(values) == (("on_delay", "2s"), ("off_delay", "500ms"))
    assert response(timed="200ms", maintained=True) == (("timed", "200ms"), ("maintained", True))
    assert response(on_delay="", off_delay=None) == ()


def test_kinds_split_by_feedback_type():
    assert [kind.name for kind in kinds_for("bool")] == [
        kind.name for kind in PHYSICAL_KINDS if kind.feedback == "bool"
    ]
    assert [kind.name for kind in kinds_for("analog")] == [
        kind.name for kind in PHYSICAL_KINDS if kind.feedback == "analog"
    ]
    assert kinds_for(None) == PHYSICAL_KINDS


def test_a_form_shows_every_key_but_a_required_flag():
    shown = {kind.name: [key.name for key in shown_keys(kind)] for kind in PHYSICAL_KINDS}
    assert shown["timed"] == ["timed", "maintained"]
    assert shown["toggle"] == []
    for kind in PHYSICAL_KINDS:
        hidden = set(kind.key_names) - set(shown[kind.name])
        assert all(PHYSICAL_KEYS[name].is_flag and PHYSICAL_KEYS[name].required for name in hidden)


def test_the_kind_of_a_response():
    assert response_kind(response(flasher_on="8ms", flasher_off="8ms")).name == "flasher"
    assert response_kind(["toggle"]).name == "toggle"
    assert response_kind(()) is None
    assert response_kind(response(on_delay="1s", ramp_on="1")) is None


def test_values_are_checked_by_pyrungs_parsers():
    assert response_check(response(on_delay="2s")) == []
    assert response_check(response(approach_to="Oven_SP", approach_rate="0.3")) == []
    (error,) = response_check(response(timed="200"))
    assert error.startswith("timed:")
    assert response_check(response(ramp_on="up")) == ["ramp_on: expected a number, got 'up'"]
    assert response_check(response(maintained=True)) == ["maintained needs timed."]


def test_a_dialog_starts_each_kind_with_values_pyrung_reads():
    for kind in PHYSICAL_KINDS:
        values = response_of({key.name: key.suggested or key.is_flag for key in kind.keys})
        assert response_check(values) == [], kind.name


def test_meta_fields_replace_the_response_whole():
    meta = TagMeta(link="Run", on_delay="1s", off_delay="2s")
    meta = replace(meta, **meta_fields(response(toggle=True)))
    assert meta_response(meta) == (("toggle", True),)
    assert format_tag_meta(meta) == "[link=Run, toggle]"
    assert meta_response(replace(meta, **meta_fields(()))) == ()


def test_responses_pyrung_reads_alike_are_the_same():
    assert same_response(response(ramp_on="1.0", ramp_off="0"), response(ramp_on="1"))
    assert not same_response(response(ramp_on="1"), response(ramp_on="2"))
    assert not same_response(response(on_delay="1s"), response(off_delay="1s"))
    assert not same_response(response(ramp_on="x"), response(ramp_on="1"))


def test_the_dap_fields_round_trip():
    values = response(timed="200ms", maintained=True)
    fields = dap_arguments(values)
    assert fields == {"timed": "200ms", "maintained": True}
    row = {key.dap_field: False if key.is_flag else None for key in PHYSICAL_KEYS.values()}
    row.update(dap_arguments(response(approach_to="Oven_SP", approach_rate="0.3")))
    assert row["approachTo"] == "Oven_SP"
    assert response_from_dap(row) == response(approach_to="Oven_SP", approach_rate="0.3")


def test_labels_and_cli_options_come_from_the_keys():
    assert response_label(response(on_delay="2s", off_delay="500ms")) == (
        "on_delay=2s, off_delay=500ms"
    )
    assert response_label(response(link_ignored="x", toggle=True)) == "toggle"
    usage = cli_usage()
    for key in PHYSICAL_KEYS.values():
        assert cli_option(key) in usage
    assert cli_option(PHYSICAL_KEYS["flasher_on"]) == "--flasher-on"
