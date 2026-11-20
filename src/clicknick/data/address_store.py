"""Address store with base/overlay architecture and undo/redo support.

The store maintains three layers:
- base_state: Latest snapshot from the database (the truth)
- user_overrides: Sparse dict of unsaved edits, field -> value (the intent)
- visible_state: Computed projection of base + overrides (the view)

Key behaviors:
- Undo/Redo tracks only the overlay layer (user intent)
- External DB updates preserve user edits automatically
- Immutable rows eliminate complex locking logic
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from pyclickplc.addresses import get_addr_key, iter_address_slots
from pyclickplc.banks import (
    DEFAULT_RETENTIVE,
    INTERLEAVED_PAIRS,
    MEMORY_TYPE_TO_DATA_TYPE,
    DataType,
)
from pyclickplc.blocks import compute_all_block_ranges, find_paired_tag_index, parse_block_tag
from pyclickplc.validation import SYSTEM_NICKNAME_TYPES

from ..models.address_row import AddressRow, initial_values_differ
from ..models.validation import (
    TRIMMED_FIELDS,
    cp1252_error,
    cp1252_problems,
    trim_entry,
    validate_comment,
    validate_initial_value,
    validate_nickname,
)
from ..services.block_service import BlockService, compute_block_colors, same_block_tag
from ..services.nickname_index_service import NicknameIndexService
from .data_source import DataSource
from .edit_session import EditSession
from .file_monitor import FileMonitor
from .undo_frame import MAX_UNDO_DEPTH, UndoFrame

if TYPE_CHECKING:
    from pyclickplc.blocks import BlockTag

    from ..views.address_editor.view_builder import UnifiedView

logger = logging.getLogger(__name__)

# One row's unsaved edits, as content field -> the value the user set. It is read-only.
# After _derive has run, it holds only the fields that differ from base.
RowOverride = Mapping[str, str | bool]


def _value_differs(base_row: AddressRow, field: str, value: str | bool) -> bool:
    """Check whether setting one content field to *value* changes *base_row*.

    initial_value needs the default-aware comparison, not plain inequality. See
    initial_values_differ.
    """
    if field == "initial_value":
        return initial_values_differ(replace(base_row, initial_value=value), base_row)
    return getattr(base_row, field) != value


def _flag_loaded_error(row: AddressRow) -> AddressRow:
    """Return *row* with loaded_with_error set when CLICK holds a nickname that breaks our rules.

    This applies to X, SC and SD nicknames. CLICK writes system nicknames, such as `log` on
    SC (a reserved word), that ClickNick would refuse from the user. While the row shows the
    nickname that the database holds, the flag hides its validation errors. Every base row
    passes through here on load, reload and Sync, so the flag is the same whichever way the
    row arrived. It depends on the row alone. A duplicate name does not set it.
    """
    flagged = False
    if row.memory_type in SYSTEM_NICKNAME_TYPES and row.nickname:
        system_bank: str | None = row.memory_type
        if row.memory_type == "X" and not row.nickname.startswith("_IO"):
            system_bank = None
        is_valid, _ = validate_nickname(
            row.nickname, row.addr_key, lambda _name, _key: False, system_bank=system_bank
        )
        flagged = not is_valid
    if flagged and cp1252_problems([row]):
        # A character that CLICK cannot hold is an error to fix, never one to hide
        flagged = False
    if row.loaded_with_error == flagged:
        return row
    return replace(row, loaded_with_error=flagged)


# The undo description of the edit that trims loaded values (_stage_trims)
TRIM_DESCRIPTION = "Trim spaces"


def _is_trimmed_loaded_nickname(nickname: str, base_row: AddressRow) -> bool:
    """Return True when *nickname* is *base_row*'s flagged nickname after the trim on load.

    Example: CLICK holds ``_IO1_Module_Error `` with a space at the end, and ClickNick shows
    ``_IO1_Module_Error``. CLICK's own editor would strip that space too.
    """
    return (
        base_row.loaded_with_error
        and nickname != ""
        and nickname != base_row.nickname
        and nickname == trim_entry("nickname", base_row.nickname, base_row.data_type)
    )


def _database_row(row: AddressRow, db_row: AddressRow) -> AddressRow:
    """Return *row* with *db_row*'s database fields, flagged by _flag_loaded_error."""
    return _flag_loaded_error(
        replace(
            row,
            nickname=db_row.nickname,
            comment=db_row.comment,
            used=db_row.used,
            data_type=db_row.data_type,
            initial_value=db_row.initial_value,
            retentive=db_row.retentive,
        )
    )


class AddressStore:
    """Central data store with base/overlay architecture.

    Manages all address data with support for:
    - Undo/Redo (Ctrl+Z/Y) with configurable depth
    - External database updates that preserve user edits
    - Dirty detection by whether a row has an override
    - Observer pattern for view updates

    Usage:
        store = AddressStore(data_source)
        store.load_initial_data()

        # Edit with undo support
        with store.edit_session("Update nickname") as session:
            session.set_field(addr_key, "nickname", "NewName")

        # Undo/Redo
        store.undo()
        store.redo()
    """

    def __init__(self, data_source: DataSource):
        """Initialize the address store.

        Args:
            data_source: DataSource implementation for loading/saving data
        """
        self._data_source = data_source

        # The three layers
        self.base_state: dict[int, AddressRow] = {}
        self.user_overrides: dict[int, RowOverride] = {}
        self.visible_state: dict[int, AddressRow] = {}
        self.loaded_row_count = 0

        # Display order (addr_keys in the order they should appear)
        self.row_order: list[int] = []
        self._row_position: dict[int, int] = {}
        self._keys_by_type: dict[str, list[int]] = {}  # memory type -> keys in address order

        self.undo_stack: list[UndoFrame] = []
        self.redo_stack: list[UndoFrame] = []

        # Nickname index service for O(1) lookups
        self._nickname_service = NicknameIndexService()

        # Observer callbacks - called with set of affected addr_keys
        self._observers: list[Callable[[object, set[int] | None], None]] = []
        # Called after a Sync writes rows into CLICK's database (add_sync_listener)
        self._sync_listeners: list[Callable[[set[int]], None]] = []

        self._initialized = False

        self._file_monitor: FileMonitor | None = None

        # Cached unified view
        self._unified_view: UnifiedView | None = None
        self._unified_row_indices: dict[int, int] = {}

        # Current edit session (for nested check)
        self._current_session: EditSession | None = None
        # Loaded rows whose trim waits for the open edit session to end (_stage_trims)
        self._pending_trims: set[int] = set()

        # Block colors (separate from AddressRow to avoid row recreation)
        self.block_colors: dict[int, str] = {}  # addr_key -> color_name

    @property
    def supports_used_field(self) -> bool:
        """Check if the data source supports the 'Used' field."""
        return self._data_source.supports_used_field

    @property
    def is_database(self) -> bool:
        """Return True when the store reads CLICK's project database rather than a CSV export."""
        return self._data_source.is_database

    # --- Skeleton Creation ---

    def _create_base_skeleton(self) -> dict[int, AddressRow]:
        """Create base skeleton of all possible AddressRow objects.

        Creates one immutable AddressRow per valid address slot.
        These form the initial base_state before database hydration.

        Returns:
            Dict mapping addr_key to skeleton AddressRow objects
        """
        skeleton: dict[int, AddressRow] = {}

        for mem_type, addr in iter_address_slots():
            addr_key = get_addr_key(mem_type, addr)
            skeleton[addr_key] = AddressRow(
                memory_type=mem_type,
                address=addr,
                data_type=MEMORY_TYPE_TO_DATA_TYPE.get(mem_type, DataType.BIT),
                retentive=DEFAULT_RETENTIVE.get(mem_type, False),
            )
            self.row_order.append(addr_key)
            self._keys_by_type.setdefault(mem_type, []).append(addr_key)

        self._row_position = {addr_key: i for i, addr_key in enumerate(self.row_order)}
        return skeleton

    def _validate_row(self, addr_key: int) -> None:
        """Validate a single row and update its validation state."""
        row = self.visible_state.get(addr_key)
        if not row:
            return

        base_row = self.base_state.get(addr_key)
        is_loaded_base_nickname = (
            base_row is not None and row.nickname != "" and base_row.nickname == row.nickname
        )
        system_bank: str | None = None
        if row.memory_type in SYSTEM_NICKNAME_TYPES:
            # Apply pyclickplc's system-name rules narrowly. On X they apply only
            # to an _IO name that is unchanged from the load.
            if row.memory_type == "X":
                # X system nicknames are auto-generated _IO* signals.
                if is_loaded_base_nickname and row.nickname.startswith("_IO"):
                    system_bank = "X"
            else:
                # SC/SD are PLC-owned system banks. Their documented names may
                # start with underscores or contain system punctuation whether
                # loaded from CLICK or repaired by the user.
                system_bank = row.memory_type

        if base_row is not None and _is_trimmed_loaded_nickname(row.nickname, base_row):
            # CLICK may hold a nickname that breaks our rules. While the row shows it
            # as loaded, loaded_with_error hides its errors. The trimmed name differs
            # from the loaded one, so the flag is off. Skip the format rules for it,
            # as the flag did, but check it for duplicates.
            if error := cp1252_error(row.nickname):
                nickname_valid, nickname_error = False, error
            elif self.is_duplicate_nickname(row.nickname, addr_key):
                nickname_valid, nickname_error = False, "Duplicate"
            else:
                nickname_valid, nickname_error = True, ""
        else:
            nickname_valid, nickname_error = validate_nickname(
                row.nickname,
                addr_key,
                self.is_duplicate_nickname,
                system_bank=system_bank,
            )

        # Validate comment (includes block name uniqueness check)
        comment_valid, comment_error = validate_comment(
            row.comment, self.is_duplicate_block_name, addr_key
        )

        init_valid, init_error = validate_initial_value(row.initial_value, row.data_type)

        is_valid = nickname_valid and comment_valid and init_valid

        # Only update if validation state changed
        if (
            row.is_valid != is_valid
            or row._nickname_valid != nickname_valid
            or row.nickname_error != nickname_error
            or row.comment_valid != comment_valid
            or row.comment_error != comment_error
            or row.initial_value_valid != init_valid
            or row.initial_value_error != init_error
        ):
            validation = {
                "is_valid": is_valid,
                "_nickname_valid": nickname_valid,
                "nickname_error": nickname_error,
                "comment_valid": comment_valid,
                "comment_error": comment_error,
                "initial_value_valid": init_valid,
                "initial_value_error": init_error,
            }
            # Validation is derived state. It lives on visible rows only, never on overrides,
            # because overrides are user input and undo frames capture them.
            self.visible_state[addr_key] = replace(row, **validation)

    def _validate_all_rows(self) -> None:
        """Validate all rows and update validation state."""
        for addr_key in self.visible_state:
            self._validate_row(addr_key)

    def _validate_affected_rows(
        self, affected: set[int], nickname_changes: dict[int, str]
    ) -> set[int]:
        """Validate rows affected by changes."""
        # Collect all nicknames involved for duplicate detection cascade
        nicknames_to_check: set[str] = set()

        for addr_key, old_nickname in nickname_changes.items():
            if old_nickname:
                nicknames_to_check.add(old_nickname.lower())
            if addr_key in self.visible_state:
                new_nick = self.visible_state[addr_key].nickname
                if new_nick:
                    nicknames_to_check.add(new_nick.lower())

        # Find all rows with these nicknames
        keys_to_validate = affected.copy()
        for nickname in nicknames_to_check:
            keys_to_validate.update(self._nickname_service.get_addr_keys_insensitive(nickname))

        for addr_key in keys_to_validate:
            self._validate_row(addr_key)

        return keys_to_validate

    # --- Nickname Index ---

    def _rebuild_nickname_index(self) -> None:
        """Rebuild the nickname reverse index."""
        self._nickname_service.rebuild_index(self.visible_state.values())

    def _sync_unified_view(self, affected_keys: set[int] | None) -> None:
        """Replace cached immutable rows with their current visible versions."""
        view = self._unified_view
        if view is None:
            return

        keys = self.visible_state.keys() if affected_keys is None else affected_keys
        for addr_key in keys:
            row_idx = self._unified_row_indices.get(addr_key)
            current = self.visible_state.get(addr_key)
            if row_idx is not None and current is not None:
                view.rows[row_idx] = current

    def _notify_observers(self, affected_keys: set[int] | None = None) -> None:
        """Notify all observers of data changes."""
        self._sync_unified_view(affected_keys)
        for callback in self._observers:
            try:
                callback(self, affected_keys)
            except Exception:
                # Don't let one observer's error break others, but never hide it.
                logger.exception("AddressStore observer %r failed", callback)

    def _default_database_row(self, row: AddressRow) -> AddressRow:
        """Return the skeleton/base row for an address missing from the database."""
        return AddressRow(
            memory_type=row.memory_type,
            address=row.address,
            data_type=MEMORY_TYPE_TO_DATA_TYPE.get(row.memory_type, DataType.BIT),
            retentive=DEFAULT_RETENTIVE.get(row.memory_type, False),
        )

    def _merge_base_with_override(self, addr_key: int, base_row: AddressRow) -> AddressRow:
        """Apply the user's override values on top of a base row.

        Fields the user did not set stay at their base values. External database changes
        to those fields show even while the row has other pending edits.
        """
        override = self.user_overrides.get(addr_key)
        if not override:
            return base_row
        merged = replace(base_row, **override)
        return replace(
            merged,
            loaded_with_error=base_row.loaded_with_error and merged.nickname == base_row.nickname,
        )

    def _rebase_override(self, addr_key: int) -> None:
        """Drop override fields whose value the current base row already holds.

        A field that holds the base value is not an edit. is_dirty() only checks whether an
        override exists. If such a field stayed, the row would count as changed. It would be
        listed under "Changed" and written on Sync, although no cell differs. An override can
        come to hold the base value in three ways:

        - You type the value back, or import a CSV that already matches the project.
        - CLICK saves the value you typed, so the base row now holds it.
        - Undo restores a frame that was recorded before a save.

        Once the field is dropped, later base changes to it show through. An override with no
        fields left is removed.
        """
        override = self.user_overrides.get(addr_key)
        base_row = self.base_state.get(addr_key)
        if override is None or base_row is None:
            return

        kept = {
            field: value
            for field, value in override.items()
            if _value_differs(base_row, field, value)
        }
        if len(kept) == len(override):
            return
        if kept:
            self.user_overrides[addr_key] = MappingProxyType(kept)
        else:
            del self.user_overrides[addr_key]

    def _recompute_block_colors(self, affected: set[int]) -> set[int]:
        """Recompute block colors for the entire unified view.

        Returns:
            Updated set of affected keys (may be larger due to block ranges)
        """
        view = self.get_unified_view()
        if not view:
            return affected

        # Refresh view rows from visible_state first
        # (immutable architecture creates new row objects on edit, so view.rows becomes stale)
        for idx, row in enumerate(view.rows):
            current = self.visible_state.get(row.addr_key)
            if current is not None and current is not row:
                view.rows[idx] = current

        color_map = compute_block_colors(view.rows)

        all_affected = set(affected)
        for row_idx, row in enumerate(view.rows):
            new_color = color_map.get(row_idx)
            old_color = self.block_colors.get(row.addr_key)
            if old_color != new_color:
                if new_color:
                    self.block_colors[row.addr_key] = new_color
                else:
                    self.block_colors.pop(row.addr_key, None)
                all_affected.add(row.addr_key)

        return all_affected

    def _recompute_visible(self, affected_keys: set[int]) -> None:
        """Recompute visible_state for affected keys."""
        for addr_key in affected_keys:
            base = self.base_state.get(addr_key)
            if base is not None:
                self.visible_state[addr_key] = self._merge_base_with_override(addr_key, base)

    def _update_nickname_index(self, nickname_changes: dict[int, str]) -> None:
        """Update nickname reverse index after changes."""
        for addr_key, old_nickname in nickname_changes.items():
            new_nickname = (
                self.visible_state[addr_key].nickname if addr_key in self.visible_state else ""
            )
            if old_nickname != new_nickname:
                self._nickname_service.update(addr_key, old_nickname, new_nickname)

    def _keys_defining_blocks(self, names: set[str]) -> set[int]:
        """Return keys whose comment opens or self-closes a block with one of these names.

        Validation checks block-name uniqueness across rows. When a block tag changes,
        every other definition of that name must be validated again.
        """
        if not names:
            return set()
        keys: set[int] = set()
        for addr_key, row in self.visible_state.items():
            if "<" not in row.comment:
                continue
            tag = parse_block_tag(row.comment)
            if tag.name in names and tag.tag_type in ("open", "self-closing"):
                keys.add(addr_key)
        return keys

    def _derive(self, changed: set[int]) -> None:
        """Bring derived state up to date for changed keys, then notify.

        Every path that changes the inputs (base_state, user_overrides) ends here, so
        derived state is always computed the same way, in this order:
        1. dirty: drop override fields that base now holds (_rebase_override), so a
           field is dirty exactly when it is in its row's override
        2. visible = base merged with overrides
        3. nickname diff (visible before and after)
        4. nickname index (duplicate checks read it, so it goes before validation)
        5. validate the changed keys, every row that shares an old or new nickname, and
           every row that defines a block whose name was added or removed
        6. block colors, if any comment changed
        7. notify observers

        Args:
            changed: addr_keys whose base row or override changed
        """
        for key in changed:
            self._rebase_override(key)

        old_rows = {key: self.visible_state.get(key) for key in changed}
        self._recompute_visible(changed)

        nickname_changes: dict[int, str] = {}
        comments_changed = False
        block_names: set[str] = set()
        for key, old in old_rows.items():
            new = self.visible_state.get(key)
            old_nickname = old.nickname if old else ""
            if (new.nickname if new else "") != old_nickname:
                nickname_changes[key] = old_nickname
            old_comment = old.comment if old else ""
            new_comment = new.comment if new else ""
            if new_comment != old_comment:
                comments_changed = True
                for comment in (old_comment, new_comment):
                    name = parse_block_tag(comment).name
                    if name:
                        block_names.add(name)

        self._update_nickname_index(nickname_changes)
        to_validate = changed | self._keys_defining_blocks(block_names)
        affected = self._validate_affected_rows(to_validate, nickname_changes)
        if comments_changed:
            affected = self._recompute_block_colors(affected)

        self._notify_observers(affected)

    def _apply_database_rows(self, new_rows: Mapping[int, AddressRow]) -> None:
        """Replace the base rows with *new_rows* from a fresh read of the data source.

        Then bring derived state up to date for the rows that changed, and stage their trims.
        """
        self.loaded_row_count = len(new_rows)

        changed: set[int] = set()
        for addr_key, old_base in self.base_state.items():
            new_row = new_rows.get(addr_key)
            if new_row is None:
                # Rows absent from the database are real deletions/clears. Reset
                # the base row to the skeleton so no stale MDB content stays.
                updated_base = self._default_database_row(old_base)
            else:
                updated_base = _database_row(old_base, new_row)
            if updated_base != old_base:
                self.base_state[addr_key] = updated_base
                changed.add(addr_key)

        if changed:
            self._derive(changed)
            self._stage_trims(changed)

    def _stage_trims(self, keys: Iterable[int]) -> None:
        """Stage the trim of each loaded value that trim_entry changes.

        The values are a nickname or an initial value of any type but Text with a space or a
        tab at either end. CLICK stores neither with one. A comment is never trimmed. A value
        that was read with one, from a CSV or from a database that another tool wrote, becomes
        an unsaved edit that holds the trimmed value. It is one undo step, "Trim spaces", and
        Sync writes it. Undo puts the spaces and tabs back, and validation flags them again.

        This method looks only at the base rows in *keys*. Callers pass the rows that were
        just loaded, the rows that a read of the data source changed, or every row after a
        Discard. A trim that the user undid is therefore staged again only when the data
        source changes that row. A field that the user already edits is left alone.

        A nickname flagged ``loaded_with_error`` is trimmed too. After the trim,
        ``_validate_row`` still skips the format rules for it, but checks it for duplicates
        like any other nickname. No SC or SD name in pyclickplc's table has a space or a tab at
        either end, so a documented name is never changed. CLICK generates the X ``_IO`` names, and no table
        checks them.

        No undo step is pushed when no row needs a trim. Edit sessions do not nest. While a
        session is open, the rows wait in ``_pending_trims``. They are staged when that
        session ends or by the next call.
        """
        keys = set(keys) | self._pending_trims
        self._pending_trims = set()
        trims: list[tuple[int, str, str]] = []
        for key in keys:
            base = self.base_state.get(key)
            if base is None:
                continue
            override = self.user_overrides.get(key, {})
            for field in TRIMMED_FIELDS:
                value = getattr(base, field)
                trimmed = trim_entry(field, value, base.data_type)
                if field not in override and value != trimmed:
                    trims.append((key, field, trimmed))
        if not trims:
            return
        if self._current_session is not None:
            self._pending_trims = {key for key, _field, _value in trims}
            return
        with self.edit_session(TRIM_DESCRIPTION) as session:
            for key, field, value in trims:
                session.set_field(key, field, value)

    def _on_database_update(self) -> bool:
        """Handle external database changes."""
        try:
            new_rows = self._data_source.load_all_addresses()
        except Exception:
            return False
        self._apply_database_rows(new_rows)
        return True

    # --- Data Loading ---

    def load_initial_data(self) -> None:
        """Load all address data from data source.

        Creates base skeleton, then hydrates with database values.
        """
        self.base_state = self._create_base_skeleton()

        db_rows = self._data_source.load_all_addresses()
        self.loaded_row_count = len(db_rows)
        for addr_key, db_row in db_rows.items():
            if addr_key in self.base_state:
                self.base_state[addr_key] = _database_row(self.base_state[addr_key], db_row)

        # No overrides yet: visible rows are the base rows.
        self.visible_state = dict(self.base_state)
        self._rebuild_nickname_index()

        self._validate_all_rows()

        self._initialized = True
        self._stage_trims(self.base_state)

        self._file_monitor = FileMonitor(
            file_path=self._data_source.file_path,
            on_modified=self._on_database_update,
        )

    def _matching_tag_key(self, addr_key: int, tag: BlockTag) -> int | None:
        """Return the key of the row whose open/close tag pairs with *tag* on *addr_key*.

        The pairing reads the visible rows, which do not include the open session's edits.
        """
        if tag.tag_type not in ("open", "close"):
            return None
        keys = self._keys_by_type.get(self.visible_state[addr_key].memory_type)
        if not keys:
            return None
        rows = [self.visible_state[key] for key in keys]
        idx = self._row_position[addr_key] - self._row_position[keys[0]]
        match_idx = find_paired_tag_index(rows, idx, tag)
        return None if match_idx is None else keys[match_idx]

    def _apply_cascades(self, session: EditSession) -> None:
        """Add to *session* the edits that the caller's edits force on related rows.

        - If the caller changes Retentive on a T/TD (CT/CTD) row, the same value is set on
          its pair. Setting the value that the row already has changes nothing on the pair.
        - If a row's block tag changed (the tag, not the comment text), the matching
          open/close row's tag is renamed or removed. Then BlockService.pair_tag_comment
          updates the tag on the T/TD (CT/CTD) pair of each of those two rows. A comment
          whose tag stayed the same changes nothing else.

        This method reads what the caller set once, before any cascade writes a builder.
        A cascade never writes a field that the caller set. Old tags come from the visible
        rows, which do not change while a session is open.
        """
        caller_set = {key: builder.changes() for key, builder in session.pending.items()}
        cascaded: dict[int, str] = {}  # comments written by cascades so far

        def current_comment(addr_key: int) -> str:
            return cascaded.get(addr_key, self.visible_state[addr_key].comment)

        def write_comment(addr_key: int, comment: str | None) -> bool:
            if comment is None or "comment" in caller_set.get(addr_key, ()):
                return False
            cascaded[addr_key] = comment
            session.get_builder(addr_key).comment = comment
            return True

        def pair_key_of(row: AddressRow) -> int | None:
            pair_type = INTERLEAVED_PAIRS.get(row.memory_type)
            if pair_type is None:
                return None
            pair_key = get_addr_key(pair_type, row.address)
            return pair_key if pair_key in self.visible_state else None

        def sync_pair(row: AddressRow, old_tag: BlockTag, new_tag: BlockTag) -> None:
            pair_key = pair_key_of(row)
            if pair_key is None:
                return
            write_comment(
                pair_key,
                BlockService.pair_tag_comment(
                    current_comment(pair_key),
                    old_tag,
                    new_tag,
                    row.memory_type,
                    self.visible_state[pair_key].memory_type,
                ),
            )

        for addr_key, fields in caller_set.items():
            row = self.visible_state.get(addr_key)
            if row is None:
                continue

            pair_key = pair_key_of(row)
            if (
                pair_key is not None
                and "retentive" in fields
                and fields["retentive"] != row.retentive
                and "retentive" not in caller_set.get(pair_key, ())
            ):
                session.get_builder(pair_key).retentive = fields["retentive"]

            if "comment" not in fields:
                continue
            old_tag = parse_block_tag(row.comment)
            new_tag = parse_block_tag(fields["comment"])
            if same_block_tag(old_tag, new_tag):
                continue

            match_key = self._matching_tag_key(addr_key, old_tag)
            if match_key is not None:
                match_old = current_comment(match_key)
                match_new = BlockService.matching_tag_comment(match_old, old_tag, new_tag)
                if write_comment(match_key, match_new):
                    sync_pair(
                        self.visible_state[match_key],
                        parse_block_tag(match_old),
                        parse_block_tag(match_new),
                    )

            sync_pair(row, old_tag, new_tag)

    def _freeze_session(self, session: EditSession) -> set[int]:
        """Freeze session builders' values into user_overrides.

        A nickname and an initial value of any type but Text are frozen as CLICK stores
        them, without a space or a tab at either end (trim_entry). A comment is frozen as it
        was set. Every edit passes through here, cascades included. Values that the base row
        already holds are kept here. _derive drops them (see _rebase_override), and that is
        the one place where dirty is decided.

        Returns:
            Set of affected addr_keys
        """
        affected = set()

        for addr_key, builder in session.pending.items():
            base = self.base_state.get(addr_key)
            if base is None:
                continue
            changes = {
                field: trim_entry(field, value, base.data_type)
                for field, value in builder.changes().items()
            }
            if not changes:
                continue
            # Merge onto any existing override, so that fields set in an earlier
            # session keep their values.
            merged = {**self.user_overrides.get(addr_key, {}), **changes}
            self.user_overrides[addr_key] = MappingProxyType(merged)
            affected.add(addr_key)

        return affected

    def _commit_session(self, session: EditSession, description: str) -> None:
        """Commit pending changes from an edit session.

        This method runs these steps:
        1. Apply cascades (T/TD sync, block tags)
        2. Freeze builders into user_overrides, dropping values that base already holds
        3. If the overrides changed, push the undo frame (the overrides from before),
           clear redo, derive visible rows, index, validation and block colors, and notify.
           A session that changes nothing is not an undo step.

        If any step raises, this method restores the overrides and the undo/redo stacks,
        rebuilds derived state from them, and raises again.
        """
        saved_overrides = dict(self.user_overrides)
        saved_undo = list(self.undo_stack)
        saved_redo = list(self.redo_stack)
        try:
            self._apply_cascades(session)
            affected_keys = self._freeze_session(session)
            for key in affected_keys:
                self._rebase_override(key)
            if self.user_overrides == saved_overrides:
                return

            self.undo_stack.append(UndoFrame(overrides=saved_overrides, description=description))
            while len(self.undo_stack) > MAX_UNDO_DEPTH:
                self.undo_stack.pop(0)
            # A new edit invalidates redo history
            self.redo_stack.clear()

            self._derive(affected_keys)
        except BaseException:
            touched = set(saved_overrides) | set(self.user_overrides) | set(session.pending)
            self.user_overrides = saved_overrides
            self.undo_stack = saved_undo
            self.redo_stack = saved_redo
            self._derive(touched)
            raise

    # --- Edit Session ---

    @contextmanager
    def edit_session(self, description: str = "") -> Generator[EditSession]:
        """Context manager for making changes with undo support.

        Make all modifications inside an edit_session. On a clean exit (see _commit_session):
        1. It applies cascades (T/TD sync, block tags)
        2. It freezes builders into user_overrides, dropping values that base already holds
        3. If the overrides changed, it pushes the undo frame (the overrides from before),
           clears redo, derives visible rows, validation and block colors, and notifies
           observers. A session that changes nothing is not an undo step and notifies no one.

        If the body raises, nothing is committed.

        Args:
            description: Human-readable description for undo menu

        Yields:
            EditSession for accumulating changes
        """
        if self._current_session is not None:
            raise RuntimeError("Cannot nest edit_session calls")

        session = EditSession(self, description)
        self._current_session = session

        try:
            yield session
        except BaseException:
            # All-or-nothing: an edit that fails partway commits nothing.
            # Builders hold every pending change, so dropping them is the rollback.
            self._current_session = None
            raise

        self._current_session = None
        if session.has_pending_changes():
            self._commit_session(session, description)
        if self._pending_trims:
            self._stage_trims(())

    # --- Undo/Redo ---

    def undo(self) -> bool:
        """Restore previous override state.

        Returns:
            True if undo was performed
        """
        if not self.undo_stack:
            return False

        # The current state goes to redo under the description of the edit undone.
        frame = self.undo_stack.pop()
        self.redo_stack.append(
            UndoFrame(overrides=dict(self.user_overrides), description=frame.description)
        )

        old_overrides = self.user_overrides
        self.user_overrides = frame.overrides

        affected_keys = set(old_overrides.keys()) | set(self.user_overrides.keys())

        # The restored frame may be older than the last read of the data source.
        # _derive drops each override field that the base row now holds.
        self._derive(affected_keys)
        return True

    def redo(self) -> bool:
        """Re-apply undone changes.

        Returns:
            True if redo was performed
        """
        if not self.redo_stack:
            return False

        # The current state goes back to undo under the description of the edit redone.
        frame = self.redo_stack.pop()
        self.undo_stack.append(
            UndoFrame(overrides=dict(self.user_overrides), description=frame.description)
        )

        old_overrides = self.user_overrides
        self.user_overrides = frame.overrides

        affected_keys = set(old_overrides.keys()) | set(self.user_overrides.keys())

        # The restored frame may be older than the last read of the data source.
        # _derive drops each override field that the base row now holds.
        self._derive(affected_keys)
        return True

    def get_undo_description(self) -> str | None:
        """Get description of next undo action."""
        if self.undo_stack:
            return self.undo_stack[-1].description
        return None

    def get_redo_description(self) -> str | None:
        """Get description of next redo action."""
        if self.redo_stack:
            return self.redo_stack[-1].description
        return None

    def can_undo(self) -> bool:
        """Check if undo is available."""
        return len(self.undo_stack) > 0

    def can_redo(self) -> bool:
        """Check if redo is available."""
        return len(self.redo_stack) > 0

    # --- Block Color Access ---

    def get_block_color(self, addr_key: int) -> str | None:
        """Get block color for an address.

        Args:
            addr_key: The address key

        Returns:
            Color name (e.g., 'Red', 'Blue') or None if no color
        """
        return self.block_colors.get(addr_key)

    # --- Dirty State Queries ---

    # After _derive, every override field differs from base. A row is therefore
    # dirty exactly when it has an entry in user_overrides.

    def is_dirty(self, addr_key: int) -> bool:
        """Check if a row has unsaved edits."""
        return addr_key in self.user_overrides

    def is_field_dirty(self, addr_key: int, field: str) -> bool:
        """Check if a specific field differs from base."""
        return field in self.user_overrides.get(addr_key, ())

    def get_dirty_keys(self) -> set[int]:
        """Get all keys with unsaved edits."""
        return set(self.user_overrides)

    def has_unsaved_changes(self) -> bool:
        """Check if there are any unsaved changes."""
        return bool(self.user_overrides)

    def has_errors(self) -> bool:
        """Check if any visible rows have validation errors."""
        return any(row.has_reportable_error for row in self.visible_state.values())

    # --- Row Access ---

    def get_visible_row(self, addr_key: int) -> AddressRow | None:
        """Get visible row by addr_key."""
        return self.visible_state.get(addr_key)

    def get_base_row(self, addr_key: int) -> AddressRow | None:
        """Get base row by addr_key."""
        return self.base_state.get(addr_key)

    @property
    def all_nicknames(self) -> dict[int, str]:
        """Get dict mapping addr_key to nickname."""
        return {
            addr_key: row.nickname for addr_key, row in self.visible_state.items() if row.nickname
        }

    def get_addr_keys_for_nickname(self, nickname: str) -> set[int]:
        """Get addr_keys with exact nickname match."""
        return self._nickname_service.get_addr_keys(nickname)

    def get_addr_keys_for_nickname_insensitive(self, nickname: str) -> set[int]:
        """Get addr_keys with case-insensitive nickname match."""
        return self._nickname_service.get_addr_keys_insensitive(nickname)

    def is_duplicate_nickname(self, nickname: str, exclude_addr_key: int) -> bool:
        """Check if nickname is used by another address."""
        return self._nickname_service.is_duplicate(nickname, exclude_addr_key)

    def is_duplicate_block_name(self, block_name: str, exclude_addr_key: int) -> bool:
        """Check if block name is already defined at an earlier address.

        Block names must be unique across all memory types. A "block definition"
        is an opening tag (<Name>) or self-closing tag (<Name />). Closing tags
        (</Name>) are NOT duplicates - they're supposed to match their opening tag.

        The first definition in address order is the valid one. Later ones are duplicates.
        This method decides by position, not by edit history, so the result is the same after
        an edit as after reopening the project.

        Args:
            block_name: The block name to check
            exclude_addr_key: The addr_key to exclude (the row being validated)

        Returns:
            True if block name is defined by an earlier opening/self-closing tag
        """
        # First check: if current row has a closing tag, it's never a duplicate
        current_row = self.visible_state.get(exclude_addr_key)
        if current_row:
            current_tag = parse_block_tag(current_row.comment)
            if current_tag.tag_type == "close":
                return False  # Closing tags are allowed to match their opening tag

        own_position = self._row_position.get(exclude_addr_key)

        # Only count opening and self-closing tags as block definitions
        # Use visible_state directly (works during initial load before unified view exists)
        for addr_key, row in self.visible_state.items():
            if addr_key == exclude_addr_key or "<" not in row.comment:
                continue
            position = self._row_position.get(addr_key)
            if own_position is not None and position is not None and position > own_position:
                continue
            tag = parse_block_tag(row.comment)
            if tag.name == block_name and tag.tag_type in ("open", "self-closing"):
                return True
        return False

    # --- Observers ---

    def add_observer(self, callback: Callable[[object, set[int] | None], None]) -> None:
        """Add observer callback."""
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: Callable[[object, set[int] | None], None]) -> None:
        """Remove observer callback."""
        if callback in self._observers:
            self._observers.remove(callback)

    def add_sync_listener(self, callback: Callable[[set[int]], None]) -> None:
        """Call *callback* with the addr_keys written after each Sync that writes rows.

        The rows are written into CLICK's database. A CSV save, a Sync that writes nothing and
        a Sync that fails do not call it.
        """
        if callback not in self._sync_listeners:
            self._sync_listeners.append(callback)

    # --- File Monitoring ---

    def start_file_monitoring(self, tk_root) -> None:
        """Start monitoring the database file."""
        if self._file_monitor:
            self._file_monitor.start(tk_root)

    def stop_file_monitoring(self) -> None:
        """Stop file monitoring."""
        if self._file_monitor:
            self._file_monitor.stop()

    # --- Unified View ---

    def get_unified_view(self) -> UnifiedView | None:
        """Get the cached unified view."""
        return self._unified_view

    def set_unified_view(self, view: UnifiedView) -> None:
        """Store the unified view and compute its block colors."""
        self._unified_view = view
        self._unified_row_indices = {row.addr_key: i for i, row in enumerate(view.rows)}
        self._recompute_block_colors(set())

    # --- Save/Discard ---

    def save_all_changes(self) -> set[int]:
        """Save changes to data source.

        CLICK writes SC_.mdb while it is connected. For the database, this method first reads
        the rows again, as a file-monitor poll would. The rows it writes then carry CLICK's
        current value for every field that the user did not change. That read also decides
        whether a row is inserted, updated or deleted. An edit that the database already holds
        is not written. A CSV file is rewritten whole. Once rows are written into the
        database, this method calls the sync listeners (``add_sync_listener``).

        Returns:
            The addr_keys of the edited rows that were written. For the database, these are
            the rows that are still edits after the fresh read.

        Raises:
            RuntimeError: The data source is read-only, or rows have validation
                errors. Nothing is written.
            Exception: Whatever the data source raises reading or writing.
                Overrides and undo history are kept.
        """
        if self._data_source.is_read_only:
            raise RuntimeError("Data source is read-only")

        if not self.user_overrides:
            return set()

        writes_dirty_rows = self._data_source.supports_used_field
        if writes_dirty_rows:
            self._apply_database_rows(self._data_source.load_all_addresses())

        dirty_keys = self.get_dirty_keys()
        error_count = self.get_total_error_count() if dirty_keys else 0
        if error_count:
            rows = "1 row has" if error_count == 1 else f"{error_count} rows have"
            raise RuntimeError(f"Cannot save: {rows} validation errors. Fix them first.")

        if not writes_dirty_rows:
            # The CSV data source rewrites the whole file, so it gets every row.
            self._data_source.save_changes(list(self.visible_state.values()))
        elif dirty_keys:
            self._data_source.save_changes([self.visible_state[key] for key in dirty_keys])

        # What was written is now the base.
        for key in dirty_keys:
            self.base_state[key] = _flag_loaded_error(
                replace(self.base_state[key], **self.user_overrides[key])
            )

        affected_keys = set(self.user_overrides.keys())
        self.user_overrides.clear()

        # Sync is a commit point. An undo frame holds a snapshot of the overrides. It
        # does not hold the values that the database had before the Sync, so undo
        # could not take synced edits back out of the database.
        self.undo_stack.clear()
        self.redo_stack.clear()

        # The file monitor is deliberately not told about our own write. Its next poll reloads.
        # That reload changes nothing for what we just saved, because base already matches.
        # It still picks up anything that CLICK wrote in the meantime.
        self._derive(affected_keys)

        if writes_dirty_rows and dirty_keys:
            for listener in list(self._sync_listeners):
                try:
                    listener(set(dirty_keys))
                except Exception:
                    # The rows are already written, so a listener's error must not fail the Sync.
                    logger.exception("AddressStore sync listener %r failed", listener)

        return dirty_keys

    def discard_all_changes(self) -> None:
        """Discard all unsaved changes.

        The user confirms a Discard, and it cannot be undone. It therefore clears the undo/redo
        history too. Otherwise Undo would restore a partial snapshot.
        """
        if not self.user_overrides:
            return

        affected_keys = set(self.user_overrides.keys())
        self.user_overrides.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()

        self._derive(affected_keys)
        # The rows are back to their base values, so stage their trims again, as on load.
        self._stage_trims(self.base_state)

    # --- Statistics ---

    def is_initialized(self) -> bool:
        """Check if initial data has been loaded."""
        return self._initialized

    def get_total_modified_count(self) -> int:
        """Get total count of modified rows."""
        return len(self.get_dirty_keys())

    def get_total_error_count(self) -> int:
        """Get total count of rows with errors."""
        return sum(1 for row in self.visible_state.values() if row.has_reportable_error)

    def get_modified_count_for_type(self, memory_type: str) -> int:
        """Get count of modified rows for a memory type."""
        return sum(
            1 for key in self.get_dirty_keys() if self.visible_state[key].memory_type == memory_type
        )

    def get_error_count_for_type(self, memory_type: str) -> int:
        """Get count of rows with errors for a memory type."""
        return sum(
            1
            for row in self.visible_state.values()
            if row.memory_type == memory_type and row.has_reportable_error
        )

    # --- Block Addresses ---

    def get_block_addresses(
        self, memory_type: str
    ) -> list[tuple[int, int | None, str, str | None]]:
        """Get block definitions for a memory type, in address order."""
        rows = [
            row
            for row in (self.visible_state[key] for key in self.row_order)
            if row.memory_type == memory_type
        ]
        if not rows:
            return []

        ranges = compute_all_block_ranges(rows)

        blocks: list[tuple[int, int | None, str, str | None]] = []
        for block in ranges:
            start_addr = rows[block.start_idx].address
            if block.start_idx == block.end_idx:
                end_addr = None
            else:
                end_addr = rows[block.end_idx].address
            blocks.append((start_addr, end_addr, block.name, block.bg_color))

        return sorted(blocks, key=lambda x: x[0])
