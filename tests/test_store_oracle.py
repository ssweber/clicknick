"""Oracle test: the store's kept derived state must equal a full rebuild.

AddressStore keeps visible rows, validation, dirty markers, the nickname index,
the loaded-with-error mask and block colors up to date incrementally. Random
sequences of edits, undo, redo, discard, Sync and external CLICK writes run
against a store; after every step a second store is rebuilt from the same
inputs (database rows and the user's overrides) and every derived fact is
compared. Each edit is also checked against the cascade rules: what the caller
set holds, and other rows change only in their block tag, only when an edited
row's block tag changed.
"""

from __future__ import annotations

import random
from dataclasses import replace
from types import MappingProxyType

import pytest
from pyclickplc.addresses import get_addr_key, parse_addr_key
from pyclickplc.banks import INTERLEAVED_PAIRS
from pyclickplc.blocks import parse_block_tag

from clicknick.data.address_store import AddressStore
from clicknick.models.address_row import AddressRow, initial_values_differ
from clicknick.services.block_service import (
    compute_block_colors,
    remove_block_tag,
    same_block_tag,
)
from clicknick.views.address_editor.view_builder import build_unified_view

CONTENT_FIELDS = ("nickname", "comment", "initial_value", "retentive")
VALIDATION_FIELDS = (
    "is_valid",
    "_nickname_valid",
    "nickname_error",
    "comment_valid",
    "comment_error",
    "initial_value_valid",
    "initial_value_error",
    "loaded_with_error",
)

# Small pools so duplicates (including case-only ones), block tags and pair tags collide often.
KEYS = (
    [get_addr_key("C", n) for n in range(1, 9)]
    + [get_addr_key("DS", n) for n in (1, 2)]
    + [get_addr_key(mem, n) for mem in ("T", "TD") for n in range(1, 5)]
    + [get_addr_key(mem, n) for mem in ("CT", "CTD") for n in (1, 2)]
    + [get_addr_key(mem, n) for mem in ("X", "SC", "SD") for n in (1, 2)]
)
NICKNAMES = ["", "Alpha", "alpha", "Beta", "Gamma", "Pump_1", "log", "_IO1_Module_Error"]
COMMENTS = [
    "",
    "note",
    "<Blk>",
    "</Blk>",
    "<Blk />",
    "<Other bg='Red'>",
    "</Other>",
    "<Tm> delay",
    "</Tm>",
    "preset <Tm_D>",
    "</Tm_D>",
    "<Tm bg='Blue'>",
    "<Cnt_D /> count",
]
INITIAL_VALUES = ["", "0", "5"]
FIELD_VALUES = {
    "nickname": NICKNAMES,
    "comment": COMMENTS,
    "initial_value": INITIAL_VALUES,
    "retentive": [True, False],
}


def _row(addr_key: int, **fields) -> AddressRow:
    memory_type, address = parse_addr_key(addr_key)
    return AddressRow(memory_type=memory_type, address=address, **fields)


class Source:
    """Data source whose rows the test (as CLICK) and Sync both write."""

    supports_used_field = True
    file_path = "oracle.mdb"
    is_read_only = False
    is_database = True

    def __init__(self, rows: dict[int, AddressRow]) -> None:
        self.rows = rows

    def load_all_addresses(self) -> dict[int, AddressRow]:
        return dict(self.rows)

    def save_changes(self, rows) -> int:
        for row in rows:
            # The database keeps content, used and data type only, as SC_.mdb does.
            self.rows[row.addr_key] = _row(
                row.addr_key,
                **{name: getattr(row, name) for name in CONTENT_FIELDS},
                used=row.used,
                data_type=row.data_type,
            )
        return len(rows)


def _differs(row: AddressRow, base: AddressRow, name: str) -> bool:
    if name == "initial_value":
        return initial_values_differ(row, base)
    return getattr(row, name) != getattr(base, name)


def _rebuild(store: AddressStore, source: Source) -> AddressStore:
    """A store derived from scratch from the same inputs."""
    fresh = AddressStore(Source(dict(source.rows)))
    fresh.load_initial_data()
    # Input is what the user intends: the fields they set and the values. Which
    # of those still differ from the database is derived, here independently
    # of the store's own helpers.
    overrides = {}
    for key, values in store.user_overrides.items():
        base = fresh.base_state[key]
        kept = {
            name: value
            for name, value in values.items()
            if _differs(replace(base, **{name: value}), base, name)
        }
        if kept:
            overrides[key] = MappingProxyType(kept)
    fresh.user_overrides = overrides
    fresh._recompute_visible(set(fresh.visible_state))
    fresh._rebuild_nickname_index()
    fresh._validate_all_rows()
    return fresh


def _assert_matches_rebuild(store: AddressStore, source: Source, step: str) -> None:
    fresh = _rebuild(store, source)

    # Overrides hold values only, and only values the database does not already hold.
    assert store.user_overrides == fresh.user_overrides, (step, "overrides")

    for key in KEYS:
        kept, expected = store.visible_state[key], fresh.visible_state[key]
        for name in CONTENT_FIELDS + VALIDATION_FIELDS:
            assert getattr(kept, name) == getattr(expected, name), (step, key, name)
        assert kept.has_reportable_error == expected.has_reportable_error, (step, key)
        assert store.is_dirty(key) == fresh.is_dirty(key), (step, key, "is_dirty")
        for name in CONTENT_FIELDS:
            assert store.is_field_dirty(key, name) == fresh.is_field_dirty(key, name), (
                step,
                key,
                f"dirty {name}",
            )
        if kept.nickname:
            assert store.is_duplicate_nickname(kept.nickname, key) == fresh.is_duplicate_nickname(
                kept.nickname, key
            ), (step, key, "duplicate index")
        # The database is the base layer: it must match what CLICK holds.
        for name in CONTENT_FIELDS + ("loaded_with_error",):
            assert getattr(store.base_state[key], name) == getattr(fresh.base_state[key], name), (
                step,
                key,
                f"base {name}",
            )

    assert store.has_errors() == fresh.has_errors(), step
    assert store.has_unsaved_changes() == fresh.has_unsaved_changes(), step

    # Block colors along the unified view's row order, recomputed from scratch.
    view = store.get_unified_view()
    rows = [fresh.visible_state[row.addr_key] for row in view.rows]
    expected_colors = {
        rows[idx].addr_key: color for idx, color in compute_block_colors(rows).items()
    }
    assert store.block_colors == expected_colors, step


def _assert_cascade_rules(
    before: dict[int, AddressRow],
    store: AddressStore,
    caller_set: dict[tuple[int, str], object],
    step: str,
) -> None:
    """Rows the caller set hold what was set; other rows change only as cascades may."""
    for (key, name), value in caller_set.items():
        assert not _differs(
            replace(before[key], **{name: value}), store.visible_state[key], name
        ), (
            step,
            key,
            name,
            "caller's value",
        )

    tag_changed = any(
        not same_block_tag(parse_block_tag(before[key].comment), parse_block_tag(value))
        for (key, name), value in caller_set.items()
        if name == "comment"
    )
    retentive_pairs = {
        get_addr_key(INTERLEAVED_PAIRS[before[key].memory_type], before[key].address)
        for (key, name) in caller_set
        if name == "retentive" and before[key].memory_type in INTERLEAVED_PAIRS
    }
    for key, old in before.items():
        new = store.visible_state[key]
        for name in ("nickname", "initial_value"):
            if (key, name) not in caller_set:
                assert getattr(new, name) == getattr(old, name), (step, key, name, "cascaded")
        if (key, "retentive") not in caller_set and key not in retentive_pairs:
            assert new.retentive == old.retentive, (step, key, "retentive cascaded")
        if (key, "comment") not in caller_set and new.comment != old.comment:
            assert tag_changed, (step, key, "comment changed by a free-text edit")
            # A cascade adds, renames or removes the tag; the rest stays as it was.
            assert remove_block_tag(new.comment) == remove_block_tag(old.comment), (
                step,
                key,
                old.comment,
                new.comment,
            )


def _tied_keys(store: AddressStore, key: int) -> list[int]:
    """Rows a cascade from *key* may write: its T/TD (CT/CTD) pair and rows of
    its memory type holding a tag of the same block (its open/close match among them)."""
    row = store.visible_state[key]
    tied = []
    if row.memory_type in INTERLEAVED_PAIRS:
        tied.append(get_addr_key(INTERLEAVED_PAIRS[row.memory_type], row.address))
    name = parse_block_tag(row.comment).name
    if name is not None:
        tied += [
            other
            for other in KEYS
            if other != key
            and store.visible_state[other].memory_type == row.memory_type
            and parse_block_tag(store.visible_state[other].comment).name == name
        ]
    return tied


def _random_edit(rng: random.Random, store: AddressStore) -> str:
    edits = []
    caller_set: dict[tuple[int, str], object] = {}
    before = {key: store.visible_state[key] for key in KEYS}

    def set_field(session, key: int, name: str, value) -> None:
        session.set_field(key, name, value)
        caller_set[(key, name)] = value
        edits.append(f"{key}.{name}={value!r}")

    with store.edit_session("random edit") as session:
        for _ in range(rng.randint(1, 3)):
            key = rng.choice(KEYS)
            name = rng.choice(
                (
                    "nickname",
                    "nickname",
                    "comment",
                    "comment",
                    "comment",
                    "initial_value",
                    "retentive",
                )
            )
            set_field(session, key, name, rng.choice(FIELD_VALUES[name]))
            tied = _tied_keys(store, key)
            if name in ("comment", "retentive") and tied and rng.random() < 0.5:
                # The same edit sets a row a cascade from this one would write
                # (paste over both rows, Discard row changes on both).
                set_field(session, rng.choice(tied), name, rng.choice(FIELD_VALUES[name]))
    step = "edit " + ", ".join(edits)
    _assert_cascade_rules(before, store, caller_set, step)
    return step


def _fix_errors(store: AddressStore) -> str | None:
    """Put each row in error back as the database has it, or empty it if the
    database's row is in error too, as a user does before Sync. Returns the step."""
    caller_set: dict[tuple[int, str], object] = {}
    before = {key: store.visible_state[key] for key in KEYS}
    for _ in range(3):
        in_error = [key for key in KEYS if store.visible_state[key].has_reportable_error]
        if not in_error:
            break
        with store.edit_session("fix errors") as session:
            for key in in_error:
                base = store.base_state[key]
                fixes = {"nickname": base.nickname, "comment": base.comment}
                if not store.is_dirty(key):
                    fixes = {"nickname": "", "comment": ""}
                for name, value in fixes.items():
                    session.set_field(key, name, value)
                    caller_set[(key, name)] = value
    if not caller_set:
        return None
    step = f"fix errors on {sorted({key for key, _ in caller_set})}"
    _assert_cascade_rules(before, store, caller_set, step)
    return step


def _random_click_change(
    rng: random.Random, store: AddressStore, source: Source, *, beside_edits: bool = False
) -> tuple[int, str, str]:
    """CLICK writes one field. *beside_edits*: mostly a field the user did not set
    on a row they edited, which Sync must not put back."""
    beside = [
        (key, name)
        for key, values in store.user_overrides.items()
        for name in ("nickname", "comment")
        if name not in values
    ]
    if beside_edits and beside and rng.random() < 0.8:
        key, name = rng.choice(sorted(beside))
        # Comments mostly: a new nickname often collides and Sync refuses.
        if name == "nickname" and rng.random() < 0.5:
            value = rng.choice(NICKNAMES)
        else:
            value = rng.choice(["changed in CLICK", "note", ""])
        current = source.rows.get(key) or _row(key)
        source.rows[key] = replace(current, **{name: value})
        return key, name, value

    pending = [
        (key, name)
        for key, values in store.user_overrides.items()
        for name in values
        if name in ("nickname", "comment")
    ]
    if pending and rng.random() < 0.5:
        # CLICK saves exactly what the user has pending (typed in both places).
        key, name = rng.choice(sorted(pending))
        value = store.user_overrides[key][name]
    else:
        key = rng.choice(KEYS)
        name = rng.choice(("nickname", "comment"))
        value = rng.choice(NICKNAMES if name == "nickname" else COMMENTS)
    current = source.rows.get(key) or _row(key)
    source.rows[key] = replace(current, **{name: value})
    return key, name, value


def _save(store: AddressStore) -> bool:
    """Sync; True if it wrote. Every caller is refused while there are validation errors.

    Sync reads the database first, so whether it has errors is known only after.
    """
    had_edits = store.has_unsaved_changes()
    try:
        store.save_all_changes()
    except RuntimeError as exc:
        assert "validation errors" in str(exc)
        assert store.has_errors()
        assert store.has_unsaved_changes()
        return False
    assert not store.has_unsaved_changes()
    return had_edits


@pytest.mark.parametrize("seed", range(12))
def test_incremental_state_matches_full_rebuild(seed: int) -> None:
    rng = random.Random(seed)
    t = {n: get_addr_key("T", n) for n in (1, 3)}
    td = {n: get_addr_key("TD", n) for n in (1, 3)}
    source = Source(
        {
            KEYS[0]: _row(KEYS[0], nickname="Alpha", comment="<Blk>"),
            KEYS[3]: _row(KEYS[3], nickname="Beta", comment="</Blk>"),
            t[1]: _row(t[1], comment="<Tm> delay"),
            t[3]: _row(t[3], comment="</Tm>"),
            td[1]: _row(td[1], comment="preset <Tm_D>"),
            td[3]: _row(td[3], comment="</Tm_D>"),
            # System nicknames CLICK writes and ClickNick would refuse from the user.
            get_addr_key("SC", 1): _row(get_addr_key("SC", 1), nickname="log"),
            get_addr_key("X", 1): _row(get_addr_key("X", 1), nickname="_IO1_Module_Error"),
            get_addr_key("SD", 1): _row(get_addr_key("SD", 1), nickname="_Fixed_Scan_Time(ms)"),
        }
    )
    store = AddressStore(source)
    store.load_initial_data()
    store.set_unified_view(build_unified_view(store.visible_state))
    _assert_matches_rebuild(store, source, "load")

    history = []
    for _ in range(30):
        op = rng.choice(
            ("edit", "edit", "edit", "undo", "redo", "save", "click", "click", "stale", "discard")
        )
        if op == "edit":
            step = _random_edit(rng, store)
        elif op == "undo":
            store.undo()
            step = "undo"
        elif op == "redo":
            store.redo()
            step = "redo"
        elif op == "save":
            _save(store)
            step = "save"
        elif op == "click":
            key, name, value = _random_click_change(rng, store, source)
            store._on_database_update()
            step = f"CLICK writes {key}.{name}={value!r}"
        elif op == "stale":
            # CLICK writes between two polls and the user syncs before the next one.
            if fixed := _fix_errors(store):
                history.append(fixed)
                _assert_matches_rebuild(store, source, " -> ".join(history))
            key, name, value = _random_click_change(rng, store, source, beside_edits=True)
            user_has_field = name in store.user_overrides.get(key, {})
            _save(store)
            if not user_has_field:
                assert getattr(source.rows[key], name) == value, (key, name, "overwritten")
            store._on_database_update()  # the next poll
            step = f"CLICK writes {key}.{name}={value!r} unpolled, then save"
        else:
            store.discard_all_changes()
            step = "discard"
        history.append(step)
        _assert_matches_rebuild(store, source, " -> ".join(history))
