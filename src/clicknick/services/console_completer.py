"""Context-aware command completer for the pyrung DAP console.

Pure Python — no tkinter dependency. Parses the pyrung command registry
at runtime so clicknick stays in sync automatically when pyrung adds
new commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable


SlotKind = Literal["tag", "tags", "expression", "freeform", "choices", "flag"]


@dataclass(frozen=True)
class SlotSpec:
    """One argument slot in a command's usage string."""

    kind: SlotKind
    required: bool = True
    choices: tuple[str, ...] = ()
    label: str = ""


@dataclass(frozen=True)
class CommandSpec:
    """Parsed grammar for a single console command."""

    verb: str
    slots: tuple[SlotSpec, ...] = ()
    group: str = ""


@dataclass(frozen=True)
class CompletionResult:
    """Result of a completion query."""

    candidates: list[str] = field(default_factory=list)
    token_start: int = 0
    token_end: int = 0
    slot_kind: str = "none"
    hint: str = ""


_PAREN_RE = re.compile(r"\s*\(.*?\)\s*$")
_TAG_WORDS = {"tag", "tag2"}


def _tokenize_usage(text: str) -> list[str]:
    """Split a usage remainder into bracket-aware tokens.

    Handles ``<...>``, ``[...]``, and bare words while keeping
    bracket-delimited groups together (even with internal spaces).
    """
    tokens: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in " \t":
            i += 1
            continue
        if ch == "<":
            end = text.find(">", i)
            if end == -1:
                end = len(text) - 1
            tokens.append(text[i : end + 1])
            i = end + 1
        elif ch == "[":
            end = text.find("]", i)
            if end == -1:
                end = len(text) - 1
            tokens.append(text[i : end + 1])
            i = end + 1
        else:
            end = i
            while end < len(text) and text[end] not in " \t<[":
                end += 1
            tokens.append(text[i:end])
            i = end
    return tokens


def _classify_usage_token(token: str) -> SlotSpec | None:
    """Classify a single usage token into a SlotSpec."""
    if token == "...":
        return None

    optional = token.startswith("[")
    inner = token.strip("<>[]").strip()

    if not inner:
        return None

    # Flag: [--settled], [--paced], [--harness ...]
    if inner.startswith("--"):
        flag_name = inner.split()[0]
        return SlotSpec(kind="flag", required=False, choices=(flag_name,), label=inner)

    # Variadic tag continuation: [tag2 ...]
    base = inner.replace("...", "").strip()
    if base.lower() in _TAG_WORDS and "..." in token:
        return SlotSpec(kind="tags", required=False, label="tag")

    # Tag slot: <tag>, [tag], <tag>[@scan|:value]
    tag_part = inner.split("[")[0].split("@")[0].strip()
    if tag_part.lower() in _TAG_WORDS:
        return SlotSpec(
            kind="tag",
            required=not optional,
            label=inner,
        )

    # Choices with pipes: always|never, <install|remove|status>
    # Spaced pipes (" | ") are descriptive (e.g. "N | duration"), not literal choices
    if "|" in inner and " | " not in inner:
        parts = [p.strip() for p in inner.split("|")]
        if all(re.match(r"^[\w-]+$", p) for p in parts):
            return SlotSpec(
                kind="choices",
                required=not optional,
                choices=tuple(parts),
                label=inner,
            )
    if "|" in inner:
        return SlotSpec(kind="freeform", required=not optional, label=inner)

    # Optional single word: [clear], [off], [list], [N]
    if optional and re.match(r"^[\w-]+$", inner):
        if inner.isdigit() or inner == "N":
            return SlotSpec(kind="freeform", required=False, label=inner)
        return SlotSpec(kind="choices", required=False, choices=(inner,), label=inner)

    # Expression: contains tag names mixed with operators, offer tag completions
    if "expression" in inner.lower():
        return SlotSpec(kind="expression", required=not optional, label=inner)

    # Freeform: <value>, <filepath>, etc.
    return SlotSpec(kind="freeform", required=not optional, label=inner)


def _parse_usage(verb: str, usage: str, group: str) -> CommandSpec:
    """Parse a pyrung usage string into a CommandSpec."""
    remainder = usage.strip()
    if remainder.lower().startswith(verb):
        remainder = remainder[len(verb) :].strip()

    remainder = _PAREN_RE.sub("", remainder).strip()

    if not remainder:
        return CommandSpec(verb=verb, group=group)

    # Handle alternative forms separated by " | verb " (e.g. "record <action> | record stop")
    if f" | {verb} " in remainder:
        remainder = remainder.split("|")[0].strip()
    elif remainder.startswith("| "):
        remainder = ""

    slots: list[SlotSpec] = []
    for token in _tokenize_usage(remainder):
        slot = _classify_usage_token(token)
        if slot is not None:
            slots.append(slot)

    return CommandSpec(verb=verb, slots=tuple(slots), group=group)


def _find_token_at_cursor(text: str, cursor: int) -> tuple[list[str], str, int, int]:
    """Find the token at *cursor* and preceding completed tokens.

    Returns ``(preceding_tokens, current_token_text, token_start, token_end)``.
    """
    before = text[:cursor]

    if not before or before.endswith(" "):
        preceding = before.split()
        return preceding, "", cursor, cursor

    parts: list[tuple[int, int]] = []
    i = 0
    while i < len(before):
        if before[i] == " ":
            i += 1
            continue
        start = i
        while i < len(before) and before[i] != " ":
            i += 1
        parts.append((start, i))

    if not parts:
        return [], "", cursor, cursor

    last_start, last_end = parts[-1]
    preceding = [before[s:e] for s, e in parts[:-1]]
    current = before[last_start:last_end]
    return preceding, current, last_start, last_end


def _prefix_filter(items: list[str], prefix: str) -> list[str]:
    if not prefix:
        return items
    lower = prefix.lower()
    return [item for item in items if item.lower().startswith(lower)]


class ConsoleCompleter:
    """Context-aware command completer for the pyrung DAP console."""

    def __init__(self) -> None:
        self._specs: dict[str, CommandSpec] = {}
        self._verbs: list[str] = []
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load_grammar(self) -> None:
        """Import pyrung console modules and parse ``_REGISTRY``."""
        if self._loaded:
            return

        try:
            import pyrung.dap.bounds_console  # noqa: F401
            import pyrung.dap.capture  # noqa: F401
            import pyrung.dap.harness_console  # noqa: F401
            import pyrung.dap.miner_console  # noqa: F401
            import pyrung.dap.reload_console  # noqa: F401
            import pyrung.dap.spec_console  # noqa: F401
            from pyrung.dap.console import _REGISTRY
        except ImportError:
            return

        for verb, (_handler, usage, group) in _REGISTRY.items():
            self._specs[verb] = _parse_usage(verb, usage, group)
        self._verbs = sorted(self._specs)
        self._loaded = True

    def load_from_specs(self, specs: dict[str, CommandSpec]) -> None:
        """Load grammar from pre-built specs (for testing)."""
        self._specs = dict(specs)
        self._verbs = sorted(self._specs)
        self._loaded = True

    def _resolve_slot(
        self, spec: CommandSpec, slot_idx: int, current_token: str = ""
    ) -> SlotSpec | None:
        """Find the slot at *slot_idx*, handling variadic/greedy slots."""
        if not spec.slots:
            return None

        if slot_idx < len(spec.slots):
            return spec.slots[slot_idx]

        # Past the defined slots -- resolve greedy/repeating slots
        flags = [s for s in spec.slots if s.kind == "flag"]

        # If current token starts with "-", prefer flag completion
        if current_token.startswith("-") and flags:
            return SlotSpec(
                kind="flag", required=False, choices=sum((s.choices for s in flags), ())
            )

        # Greedy slots consume all remaining tokens
        for slot in reversed(spec.slots):
            if slot.kind in ("tags", "expression"):
                return slot

        # Fall back to flags if available
        if flags:
            return SlotSpec(
                kind="flag", required=False, choices=sum((s.choices for s in flags), ())
            )
        return None

    def _complete_slot(
        self,
        slot: SlotSpec,
        prefix: str,
        tok_start: int,
        tok_end: int,
        tag_provider: Callable[[str], list[str]] | None,
    ) -> CompletionResult:
        if slot.kind in ("tag", "tags", "expression"):
            if tag_provider is not None:
                candidates = tag_provider(prefix)
            else:
                candidates = []
            return CompletionResult(
                candidates=candidates,
                token_start=tok_start,
                token_end=tok_end,
                slot_kind=slot.kind,
                hint=slot.label or "tag",
            )

        if slot.kind == "choices":
            candidates = _prefix_filter(list(slot.choices), prefix)
            return CompletionResult(
                candidates=candidates,
                token_start=tok_start,
                token_end=tok_end,
                slot_kind="choices",
                hint=slot.label,
            )

        if slot.kind == "flag":
            candidates = _prefix_filter(list(slot.choices), prefix)
            return CompletionResult(
                candidates=candidates,
                token_start=tok_start,
                token_end=tok_end,
                slot_kind="flag",
                hint=slot.label,
            )

        return CompletionResult(
            token_start=tok_start,
            token_end=tok_end,
            slot_kind="freeform",
            hint=slot.label or "",
        )

    def complete(
        self,
        text: str,
        cursor: int,
        tag_provider: Callable[[str], list[str]] | None = None,
    ) -> CompletionResult:
        """Return completion candidates for the current cursor position."""
        if not self._loaded:
            return CompletionResult()

        preceding, current, tok_start, tok_end = _find_token_at_cursor(text, cursor)

        if not preceding:
            candidates = _prefix_filter(self._verbs, current)
            return CompletionResult(
                candidates=candidates,
                token_start=tok_start,
                token_end=tok_end,
                slot_kind="verb",
                hint="command",
            )

        verb = preceding[0].lower()
        spec = self._specs.get(verb)
        if spec is None:
            return CompletionResult(token_start=tok_start, token_end=tok_end)

        slot_idx = len(preceding) - 1
        slot = self._resolve_slot(spec, slot_idx, current)
        if slot is None:
            return CompletionResult(token_start=tok_start, token_end=tok_end)

        return self._complete_slot(slot, current, tok_start, tok_end, tag_provider)
