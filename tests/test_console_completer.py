"""Tests for the ConsoleCompleter service."""

from __future__ import annotations

import pytest

from clicknick.services.console_completer import (
    CommandSpec,
    ConsoleCompleter,
    SlotSpec,
    _find_token_at_cursor,
)

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
            # Mirrors pyrung's declared grammar for `how` (see pyrung.dap.grammar):
            # comma-separated targets, plus the keyword-introduced avoid clause.
            "how": CommandSpec(
                "how",
                (
                    SlotSpec("expression", True, label="target", repeat=True, separator=","),
                    SlotSpec(
                        "expression",
                        False,
                        label="avoid",
                        repeat=True,
                        separator=",",
                        keyword="avoid",
                    ),
                ),
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

    def test_multi_target_after_comma_space(self, completer: ConsoleCompleter):
        """`how A, B` — the second target completes like the first."""
        text = "how Motor_Run, Pum"
        r = completer.complete(text, len(text), _tag_provider)
        assert r.slot_kind == "expression"
        assert r.candidates == ["Pump_On"]
        # Splice must replace only the second target, leaving the first intact.
        assert text[: r.token_start] + "Pump_On" + text[r.token_end :] == "how Motor_Run, Pump_On"

    def test_multi_target_comma_no_space(self, completer: ConsoleCompleter):
        """`how A,B` — a comma with no space still starts a fresh tag."""
        text = "how Motor_Run,Pum"
        r = completer.complete(text, len(text), _tag_provider)
        assert r.candidates == ["Pump_On"]
        assert text[: r.token_start] + "Pump_On" + text[r.token_end :] == "how Motor_Run,Pump_On"

    def test_multi_target_bare_comma_returns_all_tags(self, completer: ConsoleCompleter):
        text = "how Motor_Run,"
        r = completer.complete(text, len(text), _tag_provider)
        assert r.candidates == ALL_TAGS
        assert r.token_start == len(text)

    def test_multi_target_comma_then_tilde(self, completer: ConsoleCompleter):
        """The comma and ~ prefixes compose: `how A, ~B`."""
        text = "how Motor_Run, ~Pum"
        r = completer.complete(text, len(text), _tag_provider)
        assert r.candidates == ["Pump_On"]
        assert text[: r.token_start] + "Pump_On" + text[r.token_end :] == "how Motor_Run, ~Pump_On"

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
# Grammar loading (integration, against the pinned pyrung)
# ---------------------------------------------------------------------------


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

    def test_how_slots_all_offer_tags(self):
        """Every `how` slot — target and avoid — must complete tags.

        The grammar comes from pyrung; a change there can silently downgrade a slot
        to freeform and kill completion. Pin it against real pyrung.
        """
        c = ConsoleCompleter()
        c.load_grammar()
        spec = c._specs["how"]
        assert spec.slots, "how has no parsed slots"
        assert all(s.kind == "expression" for s in spec.slots), spec.slots

    def test_how_grammar_carries_comma_and_keyword_metadata(self):
        """pyrung's published grammar carries what its usage prose cannot: the
        comma separator and the `avoid` keyword."""
        c = ConsoleCompleter()
        c.load_grammar()
        slots = c._specs["how"].slots
        target = slots[0]
        assert target.repeat is True
        assert target.separator == ","
        assert {s.keyword for s in slots if s.keyword} == {"avoid"}

    def test_how_completes_second_target_against_real_grammar(self):
        c = ConsoleCompleter()
        c.load_grammar()
        text = "how Motor_Run, Pum"
        r = c.complete(text, len(text), _tag_provider)
        assert r.slot_kind == "expression"
        assert r.candidates == ["Pump_On"]

    def test_avoid_clause_completes_tags_against_real_grammar(self):
        c = ConsoleCompleter()
        c.load_grammar()
        text = "how Motor_Run avoid Pum"
        r = c.complete(text, len(text), _tag_provider)
        assert r.candidates == ["Pump_On"]

    def test_clause_keywords_are_offered_after_a_target(self):
        c = ConsoleCompleter()
        c.load_grammar()
        text = "how Motor_Run av"
        r = c.complete(text, len(text), _tag_provider)
        assert r.candidates == ["avoid"]

    def test_used_keyword_not_offered_again(self):
        c = ConsoleCompleter()
        c.load_grammar()
        text = "how Motor_Run avoid Pump_On "
        r = c.complete(text, len(text), _tag_provider)
        assert "avoid" not in r.candidates
        assert r.slot_kind == "expression"
        assert r.hint == "avoid"
