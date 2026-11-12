"""Row service for multi-row operations on AddressRow objects.

This service coordinates operations like Fill Down and Clone Structure that
affect multiple rows. All operations use the store's edit_session for changes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pyclickplc.addresses import get_addr_key
from pyclickplc.banks import INTERLEAVED_PAIRS
from pyclickplc.blocks import parse_block_tag, strip_block_tag

if TYPE_CHECKING:
    from ..data.address_store import AddressStore
    from ..data.edit_session import EditSession
    from ..models.address_row import AddressRow


class RowService:
    """Coordinates multi-row operations on AddressRow objects.

    Handles Fill Down, Clone Structure, and nickname transformations.
    All operations use EditSession for making changes.

    All methods are static as the service is stateless.
    """

    @staticmethod
    def can_fill_down(rows: list[AddressRow]) -> tuple[bool, str]:
        """Check if Fill Down can be performed on the given rows.

        Validation rules:
        - At least 2 rows required
        - First row must have a non-empty nickname containing a number
        - At least one other selected row has the first row's memory type
        - All such rows must have empty nicknames (rows of other memory types,
          such as the TD rows between T rows, are left alone)

        Args:
            rows: List of AddressRow objects to validate (in order)

        Returns:
            Tuple of (can_fill, reason_if_not).
            If can_fill is True, reason is empty string.
        """
        if len(rows) < 2:
            return False, "Select multiple rows"

        first_row = rows[0]

        # First nickname must be non-empty
        if not first_row.nickname:
            return False, "First row must have a nickname"

        # Check if nickname contains a number
        if not re.search(r"\d+", first_row.nickname):
            return False, "First nickname must contain a number"

        targets = RowService.fill_down_targets(rows)
        if not targets:
            return False, "Select more rows of the same memory type"

        # Check that all rows to fill have empty nicknames
        for row in targets:
            if row.nickname:
                return False, "Other selected rows must be empty"

        return True, ""

    @staticmethod
    def _comment_without_block_tag(comment: str) -> str:
        """The comment with the block tag the parser finds removed.

        Text around the tag is kept and runs of spaces left by the removal are
        collapsed. A closing tag elsewhere in the text is not touched.
        """
        stripped = strip_block_tag(comment)
        return " ".join(stripped.split()) if stripped != comment else comment

    @staticmethod
    def _set_copied_comment(
        session: EditSession, store: AddressStore, dest_key: int, comment: str
    ) -> None:
        """Copy a comment to a destination row, keeping a block tag the destination has.

        A destination's own tag (for example the closing row of a block the
        fill runs through) stays, with its comment, as the copy would remove it.
        """
        if parse_block_tag(store.visible_state[dest_key].comment).tag_type is not None:
            return
        session.set_field(dest_key, "comment", comment)

    @staticmethod
    def fill_down_targets(rows: list[AddressRow]) -> list[AddressRow]:
        """Rows below the first that Fill Down writes: the first row's memory type only.

        A T/TD or CT/CTD selection holds both types; only the source row's
        type is numbered.
        """
        if not rows:
            return []
        memory_type = rows[0].memory_type
        return [row for row in rows[1:] if row.memory_type == memory_type]

    @staticmethod
    def block_tag_keys(rows: list[AddressRow]) -> tuple[int, int]:
        """Address keys that get the opening and closing tags of a block over `rows`.

        `rows` are in address order. When the selection holds both rows of an
        interleaved pair (T and TD, CT and CTD), the tags go on the T/CT row at
        the first and last address and the store's pair cascade writes the
        matching `_D` tags. Otherwise they are the first and last rows.
        """
        types = {r.memory_type for r in rows}

        def tag_key(row: AddressRow) -> int:
            if row.is_interleaved_secondary and INTERLEAVED_PAIRS[row.memory_type] in types:
                return get_addr_key(INTERLEAVED_PAIRS[row.memory_type], row.address)
            return row.addr_key

        return tag_key(rows[0]), tag_key(rows[-1])

    @staticmethod
    def can_clone_structure(rows: list[AddressRow]) -> tuple[bool, str]:
        """Check if Clone Structure can be performed on the given rows.

        Validation rules:
        - At least 1 row required
        - At least one row must have a nickname containing a number

        Args:
            rows: List of AddressRow objects to validate

        Returns:
            Tuple of (can_clone, reason_if_not).
            If can_clone is True, reason is empty string.
        """
        if not rows:
            return False, "Select rows to clone"

        # Check if at least one row has a nickname with a number
        for row in rows:
            if row.nickname and re.search(r"\d+", row.nickname):
                return True, ""

        return False, "At least one nickname must contain a number"

    @staticmethod
    def validate_clone_destination(
        template_rows: list[AddressRow],
        destination_rows: list[AddressRow],
    ) -> tuple[bool, str]:
        """Validate that destination rows are suitable for cloning.

        Validation rules:
        - All destination rows must have empty nicknames
        - All destination memory types must match template memory types

        Args:
            template_rows: The source rows to clone
            destination_rows: The destination rows to fill

        Returns:
            Tuple of (is_valid, error_message).
            If is_valid is True, error_message is empty string.
        """
        template_memory_types = {row.memory_type for row in template_rows}

        for row in destination_rows:
            if row.nickname:
                return (
                    False,
                    f"Destination row {row.display_address} is not empty. "
                    "All destination rows must be empty.",
                )
            if row.memory_type not in template_memory_types:
                return (
                    False,
                    f"Destination row {row.display_address} is a different memory type "
                    f"({row.memory_type}). Clone cannot cross memory type boundaries.",
                )

        return True, ""

    @staticmethod
    def increment_nickname_suffix(
        nickname: str, increment: int
    ) -> tuple[str, int | None, int | None]:
        """Increment the rightmost number in a nickname.

        This is pure logic with no side effects, useful for both fill_down
        and clone_structure operations.

        Examples:
            - "Building1_Alm1" + 1 -> ("Building1_Alm2", 1, 2)
            - "Building1_Alm" + 1 -> ("Building2_Alm", 1, 2)
            - "Tank_Level10" + 2 -> ("Tank_Level12", 10, 12)
            - "NoNumber" + 1 -> ("NoNumber", None, None)

        Args:
            nickname: The base nickname to increment
            increment: How much to add to the number

        Returns:
            Tuple of (new_nickname, original_number, new_number).
            Numbers are None if no number was found in the nickname.
        """
        import re

        # Find all numbers in the nickname, use the rightmost one
        matches = list(re.finditer(r"\d+", nickname))
        if not matches:
            return nickname, None, None

        match = matches[-1]  # Rightmost number
        num_str = match.group()
        num = int(num_str)
        new_num = num + increment

        # Preserve leading zeros if any
        new_num_str = str(new_num).zfill(len(num_str))

        # Replace the rightmost number
        new_nickname = nickname[: match.start()] + new_num_str + nickname[match.end() :]
        return new_nickname, num, new_num

    @staticmethod
    def fill_down(
        session: EditSession,
        store: AddressStore,
        source_key: int,
        target_keys: list[int],
        increment_initial_value: bool = False,
    ) -> set[int]:
        """Fill down using a provided edit session.

        Args:
            session: The active EditSession
            store: The AddressStore instance
            source_key: Source address key
            target_keys: List of target address keys
            increment_initial_value: If True and initial_value matches nickname number,
                                      increment it along with nickname

        Returns:
            Set of affected addr_keys
        """
        return RowService.clone_structure(
            session=session,
            store=store,
            template_keys=[source_key],
            destination_keys=target_keys,
            clone_count=len(target_keys),
            increment_initial_value=increment_initial_value,
        )

    @staticmethod
    def clone_structure(
        session: EditSession,
        store: AddressStore,
        template_keys: list[int],
        destination_keys: list[int],
        clone_count: int,
        increment_initial_value: bool = False,
    ) -> set[int]:
        """Clone a structure of rows with incremented nicknames using a provided session.

        Args:
            session: The active EditSession
            store: The AddressStore instance
            template_keys: Source address keys (the template)
            destination_keys: Destination address keys
            clone_count: Number of times to clone the template
            increment_initial_value: If True and initial_value matches nickname number,
                                      increment it along with nickname

        Returns:
            Set of affected addr_keys (all destination rows)
        """
        affected = set()
        block_size = len(template_keys)

        # Build template from visible state
        template = []
        for key in template_keys:
            row = store.visible_state[key]
            template.append(
                {
                    "nickname": row.nickname,
                    # A block tag names one block; a copy would duplicate it
                    "comment": RowService._comment_without_block_tag(row.comment),
                    "initial_value": row.initial_value,
                    "retentive": row.retentive,
                }
            )

        # Apply clones
        for clone_num in range(1, clone_count + 1):
            for template_idx, tmpl in enumerate(template):
                dest_idx = (clone_num - 1) * block_size + template_idx
                dest_key = destination_keys[dest_idx]

                base_nickname = tmpl["nickname"]
                if not base_nickname:
                    # Empty row in template - still copy comment/initial_value/retentive
                    RowService._set_copied_comment(session, store, dest_key, tmpl["comment"])
                    session.set_field(dest_key, "initial_value", tmpl["initial_value"])
                    session.set_field(dest_key, "retentive", tmpl["retentive"])
                    affected.add(dest_key)
                    continue

                # Increment the rightmost number in nickname
                new_nickname, orig_num, new_num = RowService.increment_nickname_suffix(
                    base_nickname, clone_num
                )

                # Update via session
                session.set_field(dest_key, "nickname", new_nickname)
                RowService._set_copied_comment(session, store, dest_key, tmpl["comment"])

                # Copy/increment initial_value based on flag
                if tmpl["initial_value"] and orig_num is not None and increment_initial_value:
                    try:
                        init_val = int(tmpl["initial_value"])
                        if init_val == orig_num:
                            session.set_field(dest_key, "initial_value", str(new_num))
                        else:
                            session.set_field(dest_key, "initial_value", tmpl["initial_value"])
                    except ValueError:
                        session.set_field(dest_key, "initial_value", tmpl["initial_value"])
                else:
                    session.set_field(dest_key, "initial_value", tmpl["initial_value"])

                # Always copy retentive
                session.set_field(dest_key, "retentive", tmpl["retentive"])

                affected.add(dest_key)

        return affected
