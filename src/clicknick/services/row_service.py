"""Row service for multi-row operations on AddressRow objects.

This service coordinates operations like Fill Down and Clone Structure that
affect multiple rows. All operations modify skeleton rows in-place and return
affected addr_keys for targeted UI updates.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data.shared_data import SharedAddressData
    from ..models.address_row import AddressRow


class RowService:
    """Coordinates multi-row operations on skeleton AddressRow objects.

    Handles Fill Down, Clone Structure, and nickname transformations.
    All operations modify skeleton rows IN-PLACE and return affected keys.

    All methods are static as the service is stateless.
    """

    @staticmethod
    def can_fill_down(rows: list[AddressRow]) -> tuple[bool, str]:
        """Check if Fill Down can be performed on the given rows.

        Validation rules:
        - At least 2 rows required
        - First row must have a non-empty nickname containing a number
        - All subsequent rows must have empty nicknames

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

        # Check that all other rows have empty nicknames
        for row in rows[1:]:
            if row.nickname:
                return False, "Other selected rows must be empty"

        return True, ""

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
        shared_data: SharedAddressData,
        source_key: int,
        target_keys: list[int],
        increment_initial_value: bool = False,
    ) -> set[int]:
        """Fill down from source to target rows with incremented nicknames.

        This is a convenience wrapper around clone_structure for the special case
        where the template is a single row. It delegates to clone_structure to
        avoid code duplication.

        Copies nickname (incremented), comment, initial_value, and retentive
        from source to all target rows. Optionally increments initial_value
        if it matches the nickname's array number.

        Args:
            shared_data: The SharedAddressData instance
            source_key: Source address key
            target_keys: List of target address keys
            increment_initial_value: If True and initial_value matches nickname number,
                                      increment it along with nickname

        Returns:
            Set of affected addr_keys (source + all targets)
        """
        # Fill down is just clone_structure with a single-row template
        affected = RowService.clone_structure(
            shared_data=shared_data,
            template_keys=[source_key],
            destination_keys=target_keys,
            clone_count=len(target_keys),
            increment_initial_value=increment_initial_value,
        )
        # Include source key for backward compatibility (original fill_down included it)
        affected.add(source_key)
        return affected

    @staticmethod
    def clone_structure(
        shared_data: SharedAddressData,
        template_keys: list[int],
        destination_keys: list[int],
        clone_count: int,
        increment_initial_value: bool = False,
    ) -> set[int]:
        """Clone a structure of rows with incremented nicknames.

        Replicates a template of rows multiple times, incrementing nicknames
        in each clone. Optionally increments initial_value if it matches
        the nickname's array number.

        Args:
            shared_data: The SharedAddressData instance
            template_keys: Source address keys (the template)
            destination_keys: Destination address keys (must be clone_count * len(template_keys))
            clone_count: Number of times to clone the template
            increment_initial_value: If True and initial_value matches nickname number,
                                      increment it along with nickname

        Returns:
            Set of affected addr_keys (all destination rows)
        """
        affected = set()
        block_size = len(template_keys)

        # Build template
        template = []
        for key in template_keys:
            row = shared_data.all_rows[key]
            template.append(
                {
                    "nickname": row.nickname,
                    "comment": row.comment,
                    "initial_value": row.initial_value,
                    "retentive": row.retentive,
                }
            )

        # Apply clones
        for clone_num in range(1, clone_count + 1):
            for template_idx, tmpl in enumerate(template):
                dest_idx = (clone_num - 1) * block_size + template_idx
                dest_key = destination_keys[dest_idx]
                dest_row = shared_data.all_rows[dest_key]

                base_nickname = tmpl["nickname"]
                if not base_nickname:
                    # Empty row in template - still copy comment/initial_value/retentive
                    dest_row.comment = tmpl["comment"]
                    dest_row.initial_value = tmpl["initial_value"]
                    dest_row.retentive = tmpl["retentive"]
                    affected.add(dest_key)
                    continue

                # Increment the rightmost number in nickname
                new_nickname, orig_num, new_num = RowService.increment_nickname_suffix(
                    base_nickname, clone_num
                )

                # Update row
                dest_row.nickname = new_nickname
                dest_row.comment = tmpl["comment"]

                # Copy/increment initial_value based on flag
                if tmpl["initial_value"] and orig_num is not None and increment_initial_value:
                    # User chose to increment - check if it matches
                    try:
                        init_val = int(tmpl["initial_value"])
                        if init_val == orig_num:
                            dest_row.initial_value = str(new_num)
                        else:
                            dest_row.initial_value = tmpl["initial_value"]
                    except ValueError:
                        dest_row.initial_value = tmpl["initial_value"]
                else:
                    # Just copy as-is
                    dest_row.initial_value = tmpl["initial_value"]

                # Always copy retentive
                dest_row.retentive = tmpl["retentive"]

                # Note: Nickname index updates are handled automatically by edit_session
                # through AddressRow.__setattr__ when nickname is set
                affected.add(dest_key)

        return affected
