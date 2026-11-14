"""Context-aware command completer for the pyrung DAP console.

Pure Python — no tkinter dependency. The grammar comes from pyrung at runtime, so
clicknick stays in sync automatically when pyrung adds or changes commands.

We read ``pyrung.dap.grammar.command_grammar()`` — the published, machine-readable
contract, which pyrung tests against its own usage strings. It states what usage
prose cannot: which clauses are keyword-introduced (such as ``avoid``), and which
slots take comma-separated conjuncts (``how A, B``).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    #: The slot may be given more than once.
    repeat: bool = False
    #: What separates repeats — "," for comma-separated conjuncts (`how A, B`).
    #: A comma is then a token boundary *inside* one slot, not the end of it.
    separator: str = " "
    #: Literal word introducing this slot (`how X avoid Y`). Empty = positional.
    keyword: str = ""


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


#: pyrung's slot kinds -> ours. pyrung has no separate "tags" kind; a repeating tag
#: slot carries ``repeat=True`` instead. Its "value"/"text" are both uncompletable.
_PYRUNG_KINDS: dict[str, SlotKind] = {
    "tag": "tag",
    "expression": "expression",
    "choices": "choices",
    "flag": "flag",
    "value": "freeform",
    "text": "freeform",
}


def _from_pyrung_slot(slot: object) -> SlotSpec:
    """Convert a ``pyrung.dap.grammar.Slot`` into our :class:`SlotSpec`."""
    kind = _PYRUNG_KINDS.get(getattr(slot, "kind", ""), "freeform")
    repeat = bool(getattr(slot, "repeat", False))
    if kind == "tag" and repeat:
        kind = "tags"
    return SlotSpec(
        kind=kind,
        required=bool(getattr(slot, "required", True)),
        choices=tuple(getattr(slot, "choices", ())),
        label=str(getattr(slot, "label", "")),
        repeat=repeat,
        separator=str(getattr(slot, "separator", " ")),
        keyword=str(getattr(slot, "keyword", "")),
    )


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
        """Load the console grammar from pyrung's published ``pyrung.dap.grammar``."""
        if self._loaded:
            return

        from pyrung.dap.grammar import command_grammar

        for verb, cg in command_grammar().items():
            self._specs[verb] = CommandSpec(
                verb=verb,
                slots=tuple(_from_pyrung_slot(s) for s in cg.slots),
                group=cg.group,
            )
        self._verbs = sorted(self._specs)
        self._loaded = bool(self._specs)

    def load_from_specs(self, specs: dict[str, CommandSpec]) -> None:
        """Load grammar from pre-built specs (for testing)."""
        self._specs = dict(specs)
        self._verbs = sorted(self._specs)
        self._loaded = True

    def _resolve_slot(
        self,
        spec: CommandSpec,
        slot_idx: int,
        current_token: str = "",
        args: tuple[str, ...] = (),
    ) -> SlotSpec | None:
        """Find the slot the cursor is in, handling keyword clauses and repeats."""
        if not spec.slots:
            return None

        # Keyword clauses (`how X avoid Y`) are not positional: the most recent
        # keyword among the typed args decides which slot we are in.
        keyworded = {s.keyword.lower(): s for s in spec.slots if s.keyword}
        if keyworded:
            for tok in reversed(args):
                slot = keyworded.get(tok.lower())
                if slot is not None:
                    return slot
            positional = [s for s in spec.slots if not s.keyword]
            return positional[-1] if positional else None

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
            # A comma-separated slot (multi-target `how A,B`, union `avoid A,B`) holds
            # several conjuncts in one slot: only the text after the last comma is the
            # tag being typed. Everything before it is already-committed input.
            if slot.separator == ",":
                comma = prefix.rfind(",")
                if comma != -1:
                    prefix = prefix[comma + 1 :]
                    tok_start += comma + 1
                    # `how A, B` — the space after the comma is not part of the tag.
                    leading = len(prefix) - len(prefix.lstrip())
                    prefix = prefix[leading:]
                    tok_start += leading
            # ~ is a slot prefix (negation): strip for filtering, preserve in output
            if prefix.startswith("~"):
                prefix = prefix[1:]
                tok_start += 1
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

    def _offer_keywords(
        self,
        spec: CommandSpec,
        args: tuple[str, ...],
        current: str,
        result: CompletionResult,
    ) -> CompletionResult:
        """Append a command's unused clause keywords (for example, `avoid`) as candidates.

        Only at the start of a fresh token — mid-conjunct (`how A, av…`) a comma is
        still open, so the user is naming a tag, not opening a clause.
        """
        if "," in current or not args:
            return result
        typed = {a.lower() for a in args}
        keywords = [
            s.keyword
            for s in spec.slots
            if s.keyword and s.keyword.lower() not in typed and s.keyword.startswith(current)
        ]
        if not keywords:
            return result
        return replace(result, candidates=[*result.candidates, *keywords])

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

        args = tuple(preceding[1:])
        slot_idx = len(preceding) - 1
        slot = self._resolve_slot(spec, slot_idx, current, args)
        if slot is None:
            return CompletionResult(token_start=tok_start, token_end=tok_end)

        result = self._complete_slot(slot, current, tok_start, tok_end, tag_provider)
        return self._offer_keywords(spec, args, current, result)
