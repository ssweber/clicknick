"""Import service for CSV merge operations.

This service handles the business logic of merging CSV data into skeleton rows.
It separates data manipulation from UI concerns.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pyclickplc.addresses import get_addr_key
from pyclickplc.blocks import parse_block_tag, strip_block_tag

if TYPE_CHECKING:
    from ..data.address_store import AddressStore
    from ..data.edit_session_new import EditSession
    from ..models.address_row import AddressRow
    from ..widgets.import_csv_dialog import BlockGroup


class ImportService:
    """Service for importing and merging CSV data into address rows.

    All methods are static as the service is stateless. The caller is
    responsible for opening the AddressStore.edit_session() and passing
    the session in.
    """

    @staticmethod
    def merge_blocks(
        store: AddressStore,
        session: EditSession,
        blocks: list[BlockGroup],
        import_options_per_block: dict[int, dict[str, str]],
    ) -> int:
        """Merge CSV blocks into skeleton rows based on per-block options.

        Changes are accumulated on the session, which applies them atomically
        (with validation, cascades and notification) when it exits.

        Args:
            store: The AddressStore holding the skeleton rows
            session: The open edit session to accumulate changes on
            blocks: List of BlockGroup objects from CSV (selected blocks only)
            import_options_per_block: Dict mapping id(block) to field options.
                Each field option is a dict with keys: 'nickname', 'comment',
                'first_scan'. Values are merge modes:
                - 'Skip': Don't import this field
                - 'Overwrite': Replace existing value with CSV value
                - 'Merge': Only import if target is empty (or, for first_scan,
                  if both of its fields are still at their defaults)
                - 'Append': Append CSV value to existing (comment only)
                - 'Block Tag': Import block tag only (comment only)

                'first_scan' covers initial_value and retentive as a pair - see
                _apply_first_scan for why they cannot be imported separately.

        Returns:
            Count of rows processed
        """
        updated_count = 0

        for block in blocks:
            # Get merge options for this specific block
            block_options = import_options_per_block.get(id(block), {})
            nickname_mode = block_options.get("nickname", "Skip")
            comment_mode = block_options.get("comment", "Skip")
            first_scan_mode = block_options.get("first_scan", "Skip")

            # Process each row in this block
            for csv_row in block.rows:
                addr_key = get_addr_key(csv_row.memory_type, csv_row.address)

                # Find skeleton row
                if addr_key not in store.visible_state:
                    continue

                ImportService._apply_nickname(session, addr_key, csv_row, nickname_mode)
                ImportService._apply_comment(session, addr_key, csv_row, comment_mode)
                ImportService._apply_first_scan(store, session, addr_key, csv_row, first_scan_mode)

                updated_count += 1

        return updated_count

    @staticmethod
    def _apply_nickname(
        session: EditSession, addr_key: int, csv_row: AddressRow, mode: str
    ) -> None:
        """Apply nickname merge based on mode."""
        if not csv_row.nickname:
            return

        if mode == "Overwrite":
            session.set_field(addr_key, "nickname", csv_row.nickname)
        elif mode == "Merge" and not session.get_effective_value(addr_key, "nickname"):
            session.set_field(addr_key, "nickname", csv_row.nickname)

    @staticmethod
    def _apply_comment(session: EditSession, addr_key: int, csv_row: AddressRow, mode: str) -> None:
        """Apply comment merge based on mode."""
        if mode == "Overwrite":
            session.set_field(addr_key, "comment", csv_row.comment)
            return

        pending = session.get_effective_value(addr_key, "comment")
        current = pending if isinstance(pending, str) else ""

        if mode == "Append":
            if current and csv_row.comment:
                session.set_field(addr_key, "comment", f"{current} {csv_row.comment}")
            elif csv_row.comment:
                session.set_field(addr_key, "comment", csv_row.comment)
        elif mode == "Block Tag":
            # Extract block tag from CSV, apply to skeleton (preserve other text)
            csv_block_tag = parse_block_tag(csv_row.comment)
            if not csv_block_tag.name:
                return

            if csv_block_tag.tag_type == "open":
                new_tag = f"<{csv_block_tag.name}>"
            elif csv_block_tag.tag_type == "close":
                new_tag = f"</{csv_block_tag.name}>"
            elif csv_block_tag.tag_type == "self-closing":
                new_tag = f"<{csv_block_tag.name} />"
            else:
                return

            # Strip existing block tag from skeleton, rebuild with CSV's block tag
            comment_no_tag = strip_block_tag(current)
            if comment_no_tag:
                session.set_field(addr_key, "comment", f"{comment_no_tag} {new_tag}")
            else:
                session.set_field(addr_key, "comment", new_tag)

    @staticmethod
    def _apply_first_scan(
        store: AddressStore,
        session: EditSession,
        addr_key: int,
        csv_row: AddressRow,
        mode: str,
    ) -> None:
        """Apply initial value and retentive together, as one first-scan decision.

        The two fields are not independent: a retentive address powers up holding
        its retained value, so its initial value never applies. Importing one
        without the other can silently change what an address holds on first scan
        (e.g. setting retentive on an address whose initial value the program
        relies on). They are therefore always written as a pair.
        """
        if mode == "Overwrite":
            session.set_field(addr_key, "initial_value", csv_row.initial_value)
            session.set_field(addr_key, "retentive", csv_row.retentive)
        elif mode == "Merge":
            # Only claim addresses whose first-scan behavior is still untouched.
            # A row with either field set has a deliberate setting worth keeping.
            target = ImportService._effective_row(store, session, addr_key)
            if target.is_default_initial_value and target.is_default_retentive:
                session.set_field(addr_key, "initial_value", csv_row.initial_value)
                session.set_field(addr_key, "retentive", csv_row.retentive)

    @staticmethod
    def _effective_row(store: AddressStore, session: EditSession, addr_key: int) -> AddressRow:
        """Row as it currently stands, including changes pending in this session."""
        row = store.visible_state[addr_key]
        initial_value = session.get_effective_value(addr_key, "initial_value")
        retentive = session.get_effective_value(addr_key, "retentive")
        return replace(
            row,
            initial_value=initial_value if isinstance(initial_value, str) else row.initial_value,
            retentive=retentive if isinstance(retentive, bool) else row.retentive,
        )
