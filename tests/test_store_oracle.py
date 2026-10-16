"""Oracle test: the store's kept derived state must equal a full rebuild.

AddressStore keeps visible rows, validation, dirty markers, the nickname index
and block colors up to date incrementally. Random sequences of edits, undo,
redo, discard, Sync and external CLICK writes run against a store; after every
step a second store is rebuilt from the same inputs (database rows and the
user's overrides) and every derived fact is compared.
"""

from __future__ import annotations

import random
from dataclasses import replace
from types import MappingProxyType

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.models.address_row import AddressRow, initial_values_differ
from clicknick.services.block_service import compute_block_colors
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
)

# Small pools so duplicates (including case-only ones) and block tags collide often.
KEYS = [get_addr_key("C", n) for n in range(1, 9)] + [get_addr_key("DS", n) for n in (1, 2)]
NICKNAMES = ["", "Alpha", "alpha", "Beta", "Gamma", "Pump_1"]
COMMENTS = ["", "note", "<Blk>", "</Blk>", "<Blk />", "<Other bg='Red'>", "</Other>"]
INITIAL_VALUES = ["", "0", "5"]


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
            self.rows[row.addr_key] = row
        return len(rows)


def _row(addr_key: int, **fields) -> AddressRow:
    memory_type = "C" if addr_key in KEYS[:8] else "DS"
    address = KEYS.index(addr_key) + 1 if memory_type == "C" else KEYS.index(addr_key) - 7
    return AddressRow(memory_type=memory_type, address=address, **fields)


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
        for name in CONTENT_FIELDS:
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


def _random_edit(rng: random.Random, store: AddressStore) -> str:
    edits = []
    with store.edit_session("random edit") as session:
        for _ in range(rng.randint(1, 3)):
            key = rng.choice(KEYS)
            name = rng.choice(("nickname", "nickname", "comment", "comment", "initial_value"))
            value = rng.choice(
                {"nickname": NICKNAMES, "comment": COMMENTS, "initial_value": INITIAL_VALUES}[name]
            )
            session.set_field(key, name, value)
            edits.append(f"{key}.{name}={value!r}")
    return "edit " + ", ".join(edits)


def _random_click_write(rng: random.Random, store: AddressStore, source: Source) -> str:
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
    store._on_database_update()
    return f"CLICK writes {key}.{name}={value!r}"


@pytest.mark.parametrize("seed", range(6))
def test_incremental_state_matches_full_rebuild(seed: int) -> None:
    rng = random.Random(seed)
    source = Source(
        {
            KEYS[0]: _row(KEYS[0], nickname="Alpha", comment="<Blk>"),
            KEYS[3]: _row(KEYS[3], nickname="Beta", comment="</Blk>"),
        }
    )
    store = AddressStore(source)
    store.load_initial_data()
    store.set_unified_view(build_unified_view(store.visible_state))
    _assert_matches_rebuild(store, source, "load")

    history = []
    for _ in range(25):
        op = rng.choice(("edit", "edit", "edit", "undo", "redo", "save", "click", "discard"))
        if op == "edit":
            step = _random_edit(rng, store)
        elif op == "undo":
            store.undo()
            step = "undo"
        elif op == "redo":
            store.redo()
            step = "redo"
        elif op == "save":
            if store.has_errors():
                continue  # the editor refuses to Sync with validation errors
            store.save_all_changes()
            step = "save"
        elif op == "click":
            step = _random_click_write(rng, store, source)
        else:
            store.discard_all_changes()
            step = "discard"
        history.append(step)
        _assert_matches_rebuild(store, source, " -> ".join(history))
