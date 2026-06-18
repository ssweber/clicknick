"""Tests for the ConsoleCompleter service."""

from __future__ import annotations

import pytest

from clicknick.services.console_completer import (
    CommandSpec,
    ConsoleCompleter,
    SlotSpec,
    _find_token_at_cursor,
    _parse_usage,
)

# ---------------------------------------------------------------------------
# Usage string parsing
# ---------------------------------------------------------------------------


class TestParseUsage:
    def test_no_args(self):
        spec = _parse_usage("continue", "continue", "execution")
        assert spec.verb == "continue"
        assert spec.slots == ()
        assert spec.group == "execution"

    def test_single_tag(self):
        spec = _parse_usage("unforce", "unforce <tag>", "data")
        assert len(spec.slots) == 1
        assert spec.slots[0].kind == "tag"
        assert spec.slots[0].required is True

    def test_tag_and_value(self):
        spec = _parse_usage("force", "force <tag> <value>", "data")
        assert len(spec.slots) == 2
        assert spec.slots[0].kind == "tag"
        assert spec.slots[1].kind == "freeform"
        assert spec.slots[1].label == "value"

    def test_multi_tag(self):
        spec = _parse_usage("get", "get <tag> [tag2 ...]", "data")
        assert len(spec.slots) == 2
        assert spec.slots[0].kind == "tag"
        assert spec.slots[0].required is True
        assert spec.slots[1].kind == "tags"
        assert spec.slots[1].required is False

    def test_tag_with_suffix(self):
        spec = _parse_usage("cause", "cause <tag>[@scan|:value]", "analysis")
        assert spec.slots[0].kind == "tag"

    def test_bare_choices(self):
        spec = _parse_usage(
            "prove", "prove always|never <expression> [--settled] [--paced]", "analysis"
        )
        assert spec.slots[0].kind == "choices"
        assert spec.slots[0].choices == ("always", "never")

    def test_angle_bracket_choices(self):
        spec = _parse_usage("harness", "harness <install|remove|status>", "capture")
        assert spec.slots[0].kind == "choices"
        assert set(spec.slots[0].choices) == {"install", "remove", "status"}

    def test_optional_choice(self):
        spec = _parse_usage("bounds", "bounds [clear]", "data")
        assert spec.slots[0].kind == "choices"
        assert spec.slots[0].required is False
        assert spec.slots[0].choices == ("clear",)

    def test_optional_off(self):
        spec = _parse_usage("autoreload", "autoreload [off]", "execution")
        assert spec.slots[0].kind == "choices"
        assert spec.slots[0].choices == ("off",)

    def test_flags(self):
        spec = _parse_usage(
            "prove", "prove always|never <expression> [--settled] [--paced]", "analysis"
        )
        flags = [s for s in spec.slots if s.kind == "flag"]
        assert len(flags) == 2
        assert flags[0].choices == ("--settled",)
        assert flags[1].choices == ("--paced",)

    def test_optional_n(self):
        spec = _parse_usage("step", "step [N]", "execution")
        assert spec.slots[0].kind == "freeform"
        assert spec.slots[0].required is False

    def test_freeform_duration(self):
        spec = _parse_usage("run", "run <N | duration>  (e.g. 10, 500ms, 2 s)", "execution")
        assert len(spec.slots) == 1
        assert spec.slots[0].kind == "freeform"

    def test_expression_slot(self):
        spec = _parse_usage("how", "how <expression> [avoid <expression>]", "analysis")
        assert spec.slots[0].kind == "expression"

    def test_prove_expression_after_choices(self):
        spec = _parse_usage(
            "prove", "prove always|never <expression> [--settled] [--paced]", "analysis"
        )
        assert spec.slots[1].kind == "expression"

    def test_alternative_forms(self):
        spec = _parse_usage("record", "record <action> | record stop", "capture")
        assert spec.slots[0].kind == "freeform"

    def test_optional_tag(self):
        spec = _parse_usage("simplified", "simplified [tag]", "analysis")
        assert spec.slots[0].kind == "tag"
        assert spec.slots[0].required is False

    def test_help(self):
        spec = _parse_usage("help", "help", "")
        assert spec.slots == ()

    def test_note(self):
        spec = _parse_usage("note", "note <text>", "data")
        assert spec.slots[0].kind == "freeform"
        assert spec.slots[0].label == "text"


# ---------------------------------------------------------------------------
# Token boundary detection
# ---------------------------------------------------------------------------


class TestFindTokenAtCursor:
    def test_empty(self):
        preceding, current, start, end = _find_token_at_cursor("", 0)
        assert preceding == []
        assert current == ""
        assert start == 0

    def test_single_token(self):
        preceding, current, start, end = _find_token_at_cursor("get", 3)
        assert preceding == []
        assert current == "get"
        assert start == 0
        assert end == 3

    def test_after_space(self):
        preceding, current, start, end = _find_token_at_cursor("get ", 4)
        assert preceding == ["get"]
        assert current == ""
        assert start == 4

    def test_mid_second_token(self):
        preceding, current, start, end = _find_token_at_cursor("get Mot", 7)
        assert preceding == ["get"]
        assert current == "Mot"
        assert start == 4
        assert end == 7

    def test_three_tokens(self):
        preceding, current, start, end = _find_token_at_cursor("force Motor_Run val", 19)
        assert preceding == ["force", "Motor_Run"]
        assert current == "val"
        assert start == 16


# ---------------------------------------------------------------------------
# Completion logic
# ---------------------------------------------------------------------------


ALL_TAGS = ["Motor_Run", "Motor_Start", "Pump_On", "Temperature"]


def _tag_provider(prefix: str) -> list[str]:
    if not prefix:
        return ALL_TAGS
    lower = prefix.lower()
    return [t for t in ALL_TAGS if t.lower().startswith(lower)]


def _make_completer() -> ConsoleCompleter:
    c = ConsoleCompleter()
    c.load_from_specs(
        {
            "get": CommandSpec("get", (SlotSpec("tag", True), SlotSpec("tags", False)), "data"),
            "force": CommandSpec(
                "force",
                (SlotSpec("tag", True), SlotSpec("freeform", True, label="value")),
                "data",
            ),
            "continue": CommandSpec("continue", (), "execution"),
            "bounds": CommandSpec(
                "bounds", (SlotSpec("choices", False, choices=("clear",)),), "data"
            ),
            "prove": CommandSpec(
                "prove",
                (
                    SlotSpec("choices", True, choices=("always", "never")),
                    SlotSpec("expression", True, label="expression"),
                    SlotSpec("flag", False, choices=("--settled", "--paced")),
                ),
                "analysis",
            ),
            "harness": CommandSpec(
                "harness",
                (SlotSpec("choices", True, choices=("install", "remove", "status")),),
                "capture",
            ),
            "how": CommandSpec(
                "how",
                (SlotSpec("expression", True, label="expression"),),
                "analysis",
            ),
        }
    )
    return c


class TestComplete:
    @pytest.fixture()
    def completer(self) -> ConsoleCompleter:
        return _make_completer()

    def test_empty_input_returns_all_verbs(self, completer: ConsoleCompleter):
        r = completer.complete("", 0)
        assert r.slot_kind == "verb"
        assert set(r.candidates) == {
            "get",
            "force",
            "continue",
            "bounds",
            "prove",
            "harness",
            "how",
        }

    def test_partial_verb(self, completer: ConsoleCompleter):
        r = completer.complete("fo", 2)
        assert r.candidates == ["force"]
        assert r.slot_kind == "verb"
        assert r.token_start == 0
        assert r.token_end == 2

    def test_verb_prefix_case_insensitive(self, completer: ConsoleCompleter):
        r = completer.complete("GE", 2)
        assert r.candidates == ["get"]

    def test_verb_complete_space_returns_tag(self, completer: ConsoleCompleter):
        r = completer.complete("get ", 4, _tag_provider)
        assert r.slot_kind == "tag"
        assert r.candidates == ALL_TAGS

    def test_tag_prefix_filters(self, completer: ConsoleCompleter):
        r = completer.complete("get Mot", 7, _tag_provider)
        assert r.candidates == ["Motor_Run", "Motor_Start"]
        assert r.token_start == 4
        assert r.token_end == 7

    def test_variadic_second_tag(self, completer: ConsoleCompleter):
        r = completer.complete("get Motor_Run ", 14, _tag_provider)
        assert r.slot_kind in ("tag", "tags")
        assert len(r.candidates) == len(ALL_TAGS)

    def test_variadic_third_tag(self, completer: ConsoleCompleter):
        r = completer.complete("get Motor_Run Pump_On ", 22, _tag_provider)
        assert r.slot_kind in ("tag", "tags")

    def test_freeform_slot_no_candidates(self, completer: ConsoleCompleter):
        r = completer.complete("force Motor_Run ", 16, _tag_provider)
        assert r.slot_kind == "freeform"
        assert r.candidates == []
        assert r.hint == "value"

    def test_choices_slot(self, completer: ConsoleCompleter):
        r = completer.complete("bounds ", 7)
        assert r.slot_kind == "choices"
        assert "clear" in r.candidates

    def test_choices_prefix(self, completer: ConsoleCompleter):
        r = completer.complete("prove al", 8)
        assert r.candidates == ["always"]

    def test_choices_all(self, completer: ConsoleCompleter):
        r = completer.complete("harness ", 8)
        assert set(r.candidates) == {"install", "remove", "status"}

    def test_no_args_command_past_verb(self, completer: ConsoleCompleter):
        r = completer.complete("continue ", 9)
        assert r.candidates == []

    def test_unknown_verb_no_candidates(self, completer: ConsoleCompleter):
        r = completer.complete("foobar ", 7)
        assert r.candidates == []

    def test_no_tag_provider_empty(self, completer: ConsoleCompleter):
        r = completer.complete("get ", 4)
        assert r.slot_kind == "tag"
        assert r.candidates == []

    def test_not_loaded_returns_empty(self):
        c = ConsoleCompleter()
        r = c.complete("get ", 4)
        assert r.candidates == []

    def test_flag_slot_with_dash_prefix(self, completer: ConsoleCompleter):
        r = completer.complete("prove always expr --", 20)
        assert r.slot_kind == "flag"
        assert "--settled" in r.candidates
        assert "--paced" in r.candidates

    def test_expression_slot_offers_tags(self, completer: ConsoleCompleter):
        r = completer.complete("how ", 4, _tag_provider)
        assert r.slot_kind == "expression"
        assert r.candidates == ALL_TAGS

    def test_expression_slot_filters_tags(self, completer: ConsoleCompleter):
        r = completer.complete("how Mot", 7, _tag_provider)
        assert r.candidates == ["Motor_Run", "Motor_Start"]

    def test_expression_greedy_second_token(self, completer: ConsoleCompleter):
        r = completer.complete("how Motor_Run & Pump", 20, _tag_provider)
        assert r.slot_kind == "expression"
        assert r.candidates == ["Pump_On"]

    def test_prove_expression_after_choices(self, completer: ConsoleCompleter):
        r = completer.complete("prove always Mot", 16, _tag_provider)
        assert r.slot_kind == "expression"
        assert "Motor_Run" in r.candidates

    def test_tilde_prefix_strips_for_tag_filtering(self, completer: ConsoleCompleter):
        r = completer.complete("get ~Mot", 8, _tag_provider)
        assert r.candidates == ["Motor_Run", "Motor_Start"]
        assert r.token_start == 5  # after the ~
        assert r.token_end == 8

    def test_tilde_prefix_in_expression_slot(self, completer: ConsoleCompleter):
        r = completer.complete("how ~Pum", 8, _tag_provider)
        assert r.candidates == ["Pump_On"]
        assert r.token_start == 5

    def test_bare_tilde_returns_all_tags(self, completer: ConsoleCompleter):
        r = completer.complete("get ~", 5, _tag_provider)
        assert r.candidates == ALL_TAGS
        assert r.token_start == 5


# ---------------------------------------------------------------------------
# Grammar loading (integration, requires pyrung)
# ---------------------------------------------------------------------------


def _pyrung_available() -> bool:
    try:
        import pyrung.dap.console  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _pyrung_available(), reason="pyrung not installed")
class TestGrammarLoading:
    def test_load_populates_specs(self):
        c = ConsoleCompleter()
        c.load_grammar()
        assert c.is_loaded
        assert "get" in c._specs
        assert "force" in c._specs
        assert "continue" in c._specs
        assert len(c._verbs) >= 30

    def test_get_has_tag_slot(self):
        c = ConsoleCompleter()
        c.load_grammar()
        spec = c._specs["get"]
        assert spec.slots[0].kind == "tag"

    def test_prove_has_choices(self):
        c = ConsoleCompleter()
        c.load_grammar()
        spec = c._specs["prove"]
        assert spec.slots[0].kind == "choices"
        assert "always" in spec.slots[0].choices
