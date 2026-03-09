"""Tests for clicknick.csv.token_parser."""

from __future__ import annotations

import pytest

from clicknick.csv.ast import AfCall, GenericCondition, VerticalPassThroughWire
from clicknick.csv.token_parser import parse_af_token, parse_condition_token


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ('call("normal")', "normal"),
        ('call("has""quote")', 'has"quote'),
        ('call("two""mid""quotes")', 'two"mid"quotes'),
        ('call("")', ""),
        ('call("no special chars")', "no special chars"),
    ],
)
def test_parse_af_token_decodes_quoted_string_args(token: str, expected: str) -> None:
    af = parse_af_token(token)
    assert isinstance(af, AfCall)
    assert af.name == "call"
    assert af.args == (expected,)


def test_parse_af_token_keeps_non_string_args() -> None:
    af = parse_af_token("future_call(1,[2,3])")
    assert isinstance(af, AfCall)
    assert af.args == ("1", "[2,3]")


def test_parse_af_token_handles_quoted_commas() -> None:
    af = parse_af_token('send(X001,"a,b",100)')
    assert isinstance(af, AfCall)
    assert af.args == ("X001", "a,b", "100")


def test_parse_af_token_treats_backslash_as_literal_character() -> None:
    af = parse_af_token('call("host\\name")')
    assert isinstance(af, AfCall)
    assert af.args == ("host\\name",)


@pytest.mark.parametrize(
    "token",
    [
        'call("unterminated)',
        'call("has\\"quote")',
    ],
)
def test_parse_af_token_rejects_malformed_quoted_strings(token: str) -> None:
    with pytest.raises(ValueError, match="Malformed AF"):
        parse_af_token(token)


def test_parse_condition_token_accepts_pipe_for_vertical_mid() -> None:
    condition = parse_condition_token("|")
    assert isinstance(condition, VerticalPassThroughWire)


def test_parse_condition_token_plus_falls_back_to_generic() -> None:
    condition = parse_condition_token("+")
    assert isinstance(condition, GenericCondition)
    assert condition.raw == "+"
