"""Import service for CSV merge operations.

This service handles the business logic of merging CSV data into skeleton rows.
It separates data manipulation from UI concerns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyclickplc import get_addr_key
from pyclickplc.blocks import parse_block_tag, strip_block_tag

if TYPE_CHECKING:
    from ..data.shared_data import SharedAddressData
    from ..widgets.import_csv_dialog import BlockGroup


class ImportService:
    """Service for importing and merging CSV data into address rows.

    All methods are static as the service is stateless. The caller is
    responsible for wrapping calls in SharedAddressData.edit_session().
    """

    @staticmethod
    def merge_blocks(
        shared_data: SharedAddressData,
        blocks: list[BlockGroup],
        import_options_per_block: dict[str, dict[str, str]],
    ) -> int:
        """Merge CSV blocks into skeleton rows based on per-block options.

        Must be called within an edit_session context for proper change
        tracking, validation, and notification.

        Args:
            shared_data: The SharedAddressData instance with skeleton rows
            blocks: List of BlockGroup objects from CSV
            import_options_per_block: Dict mapping block name to field options.
                Each field option is a dict with keys: 'nickname', 'comment',
                'init_val', 'retentive'. Values are merge modes:
                - 'Skip': Don't import this field
                - 'Overwrite': Replace existing value with CSV value
                - 'Merge': Only import if target is empty
                - 'Append': Append CSV value to existing (comment only)
                - 'Block Tag': Import block tag only (comment only)

        Returns:
            Count of rows processed
        """
        updated_count = 0

        for block in blocks:
            # Get merge options for this specific block
            block_options = import_options_per_block.get(block.name, {})
            nickname_mode = block_options.get("nickname", "Skip")
            comment_mode = block_options.get("comment", "Skip")
            init_val_mode = block_options.get("init_val", "Skip")
            retentive_mode = block_options.get("retentive", "Skip")

            # Process each row in this block
            for csv_row in block.rows:
                addr_key = get_addr_key(csv_row.memory_type, csv_row.address)

                # Find skeleton row
                if addr_key not in shared_data.all_rows:
                    continue

                skeleton_row = shared_data.all_rows[addr_key]

                # Apply nickname based on mode
                ImportService._apply_nickname(skeleton_row, csv_row, nickname_mode)

                # Apply comment based on mode
                ImportService._apply_comment(skeleton_row, csv_row, comment_mode)

                # Apply initial value based on mode
                ImportService._apply_initial_value(skeleton_row, csv_row, init_val_mode)

                # Apply retentive based on mode
                ImportService._apply_retentive(skeleton_row, csv_row, retentive_mode)

                updated_count += 1

        return updated_count

    @staticmethod
    def _apply_nickname(skeleton_row, csv_row, mode: str) -> None:
        """Apply nickname merge based on mode."""
        if mode == "Overwrite" and csv_row.nickname:
            skeleton_row.nickname = csv_row.nickname
        elif mode == "Merge" and csv_row.nickname and not skeleton_row.nickname:
            skeleton_row.nickname = csv_row.nickname

    @staticmethod
    def _apply_comment(skeleton_row, csv_row, mode: str) -> None:
        """Apply comment merge based on mode."""
        if mode == "Overwrite":
            skeleton_row.comment = csv_row.comment
        elif mode == "Append":
            if skeleton_row.comment and csv_row.comment:
                skeleton_row.comment = f"{skeleton_row.comment} {csv_row.comment}"
            elif csv_row.comment:
                skeleton_row.comment = csv_row.comment
        elif mode == "Block Tag":
            # Extract block tag from CSV, apply to skeleton (preserve other text)
            csv_block_tag = parse_block_tag(csv_row.comment)
            if csv_block_tag.name:
                # Strip existing block tag from skeleton
                skeleton_comment_no_tag = strip_block_tag(skeleton_row.comment)
                # Rebuild with CSV's block tag
                if csv_block_tag.tag_type == "open":
                    new_tag = f"<{csv_block_tag.name}>"
                elif csv_block_tag.tag_type == "close":
                    new_tag = f"</{csv_block_tag.name}>"
                elif csv_block_tag.tag_type == "self-closing":
                    new_tag = f"<{csv_block_tag.name} />"
                else:
                    new_tag = ""

                if new_tag:
                    if skeleton_comment_no_tag:
                        skeleton_row.comment = f"{skeleton_comment_no_tag} {new_tag}"
                    else:
                        skeleton_row.comment = new_tag

    @staticmethod
    def _apply_initial_value(skeleton_row, csv_row, mode: str) -> None:
        """Apply initial value merge based on mode."""
        if mode == "Overwrite" and csv_row.initial_value:
            skeleton_row.initial_value = csv_row.initial_value
        elif mode == "Merge" and csv_row.initial_value and not skeleton_row.initial_value:
            skeleton_row.initial_value = csv_row.initial_value

    @staticmethod
    def _apply_retentive(skeleton_row, csv_row, mode: str) -> None:
        """Apply retentive merge based on mode."""
        if mode == "Overwrite":
            skeleton_row.retentive = csv_row.retentive
        elif mode == "Merge" and not skeleton_row.retentive:
            skeleton_row.retentive = csv_row.retentive
