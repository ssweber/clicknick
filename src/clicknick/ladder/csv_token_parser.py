"""Token parsers for condition cells and AF output tokens."""

from __future__ import annotations

import re

from .csv_ast import (
    KNOWN_AF_NAMES,
    AfBlank,
    AfCall,
    AfNode,
    BlankCondition,
    ComparisonCondition,
    ConditionNode,
    ContactCondition,
    EdgeCondition,
    GenericCondition,
    VerticalMidCondition,
    VerticalTopCondition,
    WireCondition,
)
from .model import OPERAND_RE

_EDGE_RE = re.compile(r"^(rise|fall)\((.+)\)$")
_CALL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*|\.[A-Za-z_][A-Za-z0-9_]*)\((.*)\)$")
_COMPARISON_OPERATORS = ("==", "!=", "<=", ">=", "<", ">")


def _split_top_level_csv_like(value: str) -> tuple[str, ...]:
    if value.strip() == "":
        return tuple()

    parts: list[str] = []
    start = 0
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    in_quote = False
    idx = 0
    while idx < len(value):
        ch = value[idx]
        if in_quote:
            if ch == '"':
                if idx + 1 < len(value) and value[idx + 1] == '"':
                    idx += 2
                    continue
                in_quote = False
            idx += 1
            continue

        if ch == '"':
            in_quote = True
            idx += 1
            continue
        if ch == "(":
            paren_depth += 1
            idx += 1
            continue
        if ch == ")":
            if paren_depth > 0:
                paren_depth -= 1
            idx += 1
            continue
        if ch == "[":
            bracket_depth += 1
            idx += 1
            continue
        if ch == "]":
            if bracket_depth > 0:
                bracket_depth -= 1
            idx += 1
            continue
        if ch == "{":
            brace_depth += 1
            idx += 1
            continue
        if ch == "}":
            if brace_depth > 0:
                brace_depth -= 1
            idx += 1
            continue
        if ch == "," and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
            parts.append(value[start:idx].strip())
            start = idx + 1

        idx += 1

    if in_quote:
        raise ValueError("Malformed AF token arguments: unmatched quote")

    parts.append(value[start:].strip())
    return tuple(parts)


def _decode_af_string_literal(arg: str) -> str:
    if not arg:
        return arg

    if not (arg.startswith('"') or arg.endswith('"')):
        return arg

    if len(arg) < 2 or not (arg.startswith('"') and arg.endswith('"')):
        raise ValueError(f"Malformed AF quoted string argument: {arg!r}")

    chars: list[str] = []
    idx = 1
    end = len(arg) - 1
    while idx < end:
        ch = arg[idx]
        if ch != '"':
            chars.append(ch)
            idx += 1
            continue

        if idx + 1 < end and arg[idx + 1] == '"':
            chars.append('"')
            idx += 2
            continue

        raise ValueError(f"Malformed AF quoted string argument: {arg!r}")

    return "".join(chars)


def _parse_contact(token: str) -> ContactCondition | None:
    text = token.strip()
    if not text:
        return None

    negated = text.startswith("~")
    if negated:
        text = text[1:].strip()

    immediate = False
    inner = re.fullmatch(r"immediate\((.+)\)", text)
    if inner:
        immediate = True
        text = inner.group(1).strip()

    if not OPERAND_RE.fullmatch(text):
        return None

    return ContactCondition(operand=text, negated=negated, immediate=immediate)


def _parse_comparison(token: str) -> ComparisonCondition | None:
    for op in _COMPARISON_OPERATORS:
        idx = token.find(op)
        if idx < 0:
            continue
        left = token[:idx].strip()
        right = token[idx + len(op) :].strip()
        if not left or not right:
            return None
        return ComparisonCondition(left=left, op=op, right=right)
    return None


def parse_condition_token(token: str) -> ConditionNode:
    text = token.strip()
    if text == "":
        return BlankCondition()
    if text == "-":
        return WireCondition()
    if text == "T":
        return VerticalTopCondition()
    if text == "+":
        return VerticalMidCondition()

    edge_match = _EDGE_RE.fullmatch(text)
    if edge_match:
        operand = edge_match.group(2).strip()
        if OPERAND_RE.fullmatch(operand):
            return EdgeCondition(kind=edge_match.group(1), operand=operand)
        return GenericCondition(raw=token)

    contact = _parse_contact(text)
    if contact is not None:
        return contact

    comparison = _parse_comparison(text)
    if comparison is not None:
        return comparison

    return GenericCondition(raw=token)


def parse_af_token(token: str) -> AfNode:
    text = token.strip()
    if text == "":
        return AfBlank()

    m = _CALL_RE.fullmatch(text)
    if not m:
        return AfCall(name=text, args=tuple(), known=False)

    name = m.group(1)
    args_src = m.group(2).strip()
    args = tuple(_decode_af_string_literal(arg) for arg in _split_top_level_csv_like(args_src))
    return AfCall(name=name, args=args, known=name in KNOWN_AF_NAMES)
