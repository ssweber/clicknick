"""Data model for the Address Editor.

Contains AddressRow frozen dataclass with UI validation state.
Address helpers and constants are imported from pyclickplc.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pyclickplc.addresses import (
    format_address_display,
    get_addr_key,
)
from pyclickplc.banks import (
    DATA_TYPE_DISPLAY,
    DEFAULT_RETENTIVE,
    NON_EDITABLE_TYPES,
    DataType,
)


def value_notes(
    memory_type: str, data_type_display: str, retentive: bool, initial_value: str
) -> tuple[str, str]:
    """Return (initial value, retentive label) as the tooltip and Tag Browser show them.

    A part is empty when there is nothing to show. BIT rows name their Retentive
    setting ("Retentive" or "Non-retentive") when it differs from the memory type's
    default. Any row shows its initial value ("ON" for a BIT) when it is not
    retentive and the value is not the default; a retentive row's initial value is
    not used.
    """
    is_bit = data_type_display == "BIT"
    label = ""
    if is_bit and retentive != DEFAULT_RETENTIVE.get(memory_type, False):
        label = "Retentive" if retentive else "Non-retentive"
    initial = ""
    if not retentive:
        if is_bit:
            initial = "ON" if initial_value == "1" else ""
        elif initial_value and (initial_value != "0" or data_type_display == "TXT"):
            initial = initial_value
    return initial, label


@dataclass(frozen=True)
class AddressRow:
    """Immutable address row in the editor.

    This is the in-memory model for a single PLC address. Being frozen,
    new instances must be created for any changes using dataclasses.replace().

    Usage:
        # Create a row
        row = AddressRow(memory_type="X", address=1, nickname="Input1")

        # Modify by creating new instance
        from dataclasses import replace
        new_row = replace(row, nickname="NewName", comment="Updated")
    """

    # --- Identity ---
    memory_type: str  # 'X', 'Y', 'C', etc.
    address: int  # 1, 2, 3... (or 0 for XD/YD)

    # --- Content (user-editable) ---
    nickname: str = ""
    comment: str = ""
    initial_value: str = ""
    retentive: bool = False

    # --- Metadata (from DB, not user-editable) ---
    used: bool = False
    data_type: int = DataType.BIT

    # --- Validation State (computed) ---
    is_valid: bool = field(default=True, compare=False)
    validation_error: str = field(default="", compare=False)
    _nickname_valid: bool = field(default=True, compare=False)
    nickname_error: str = field(default="", compare=False)
    comment_valid: bool = field(default=True, compare=False)
    comment_error: str = field(default="", compare=False)
    initial_value_valid: bool = field(default=True, compare=False)
    initial_value_error: str = field(default="", compare=False)

    # Track if row was loaded with invalid data
    loaded_with_error: bool = field(default=False, compare=False)

    @property
    def addr_key(self) -> int:
        """Get the AddrKey for this row."""
        return get_addr_key(self.memory_type, self.address)

    @property
    def display_address(self) -> str:
        """Get the display string for this address (e.g., 'X001', 'XD0u', 'C150')."""
        return format_address_display(self.memory_type, self.address)

    @property
    def is_default_initial_value(self) -> bool:
        """Return True if the initial value is the default for its data type."""
        return (
            self.initial_value == ""
            or not self.data_type == DataType.TXT
            and str(self.initial_value) == "0"
        )

    @property
    def is_default_retentive(self) -> bool:
        """Return True if retentive matches the default for this memory_type."""
        default = DEFAULT_RETENTIVE.get(self.memory_type, False)
        return self.retentive == default

    @property
    def data_type_display(self) -> str:
        """Get human-readable data type name."""
        return DATA_TYPE_DISPLAY.get(self.data_type, "")

    @property
    def outline_suffix(self) -> str:
        """Get suffix string for outline panel (appended to nickname text).

        Format: ``  : DataType = Value, Retentive``, the parts from `value_notes`.
        """
        initial, retentive = value_notes(
            self.memory_type, self.data_type_display, self.retentive, self.initial_value
        )
        notes = ", ".join(part for part in (initial, retentive) if part)
        suffix = f"  : {self.data_type_display}"
        return f"{suffix} = {notes}" if notes else suffix

    # --- State Helper Properties ---

    @property
    def is_interleaved_secondary(self) -> bool:
        """True if this is a secondary type in an interleaved pair (TD, CTD).

        In unified view, T/TD and CT/CTD rows are interleaved (T1, TD1, T2, TD2...).
        The secondary types (TD, CTD) get alternating background color for visual
        distinction. This property abstracts that logic from the view layer.
        """
        return self.memory_type in ("TD", "CTD")

    @property
    def can_edit_initial_value(self) -> bool:
        """True if initial value can be edited for this memory type."""
        return self.memory_type not in NON_EDITABLE_TYPES

    def is_initial_value_masked(self, effective_retentive: bool) -> bool:
        """Check if initial value is masked (shows '-' and is read-only).

        Initial value is masked when:
        - Memory type allows editing (not in NON_EDITABLE_TYPES), AND
        - Retentive is enabled (either on this row or its paired T/CT row)

        For T/TD and CT/CTD pairs, retentive is stored on T/CT but affects
        both rows' initial value editability. The caller must pass the
        effective retentive value (from the paired row if applicable).

        Args:
            effective_retentive: The retentive value to check (from self or paired row)

        Returns:
            True if initial value should show '-' and reject edits
        """
        # NON_EDITABLE_TYPES (SC, SD, XD, YD) are never masked - they just can't be edited
        if self.memory_type in NON_EDITABLE_TYPES:
            return False
        return effective_retentive

    @property
    def can_edit_retentive(self) -> bool:
        """True if retentive setting can be edited for this memory type."""
        return self.memory_type not in NON_EDITABLE_TYPES

    @property
    def is_empty(self) -> bool:
        """True if row is empty"""
        return not self.has_content

    @property
    def should_ignore_validation_error(self) -> bool:
        """True if validation errors should be ignored for loaded system nicknames.

        Some SC/SD/X addresses can have PLC-generated nicknames with non-user format.
        If the row was loaded with errors, we ignore the errors for display purposes.
        """
        return self.loaded_with_error

    @property
    def nickname_valid(self) -> bool:
        """True if nickname is valid or validation errors should be ignored."""
        return self._nickname_valid or self.should_ignore_validation_error

    @property
    def has_reportable_error(self):
        return not (self.is_valid or self.is_empty or self.should_ignore_validation_error)

    @property
    def has_content(self) -> bool:
        """True if row has any user-defined content worth saving."""
        return (
            self.nickname != ""
            or self.comment != ""
            or not self.is_default_initial_value
            or not self.is_default_retentive
        )

    # --- CRUD Helper Properties (for save logic) ---

    def needs_full_delete(self, is_dirty: bool) -> bool:
        """True if should DELETE the entire row from database."""
        return is_dirty and not self.has_content and not self.used


def initial_values_differ(a: AddressRow, b: AddressRow) -> bool:
    """Compare two rows' initial values, treating "" and "0" as the same default.

    A defaulted numeric is written as "0" by Click's CSV export but held as "" by a
    store skeleton or baseline row. Comparing the strings raw would report every
    defaulted numeric address as changed on import. is_default_initial_value knows
    which spellings count as default for the row's data type ("0" is a real value
    for TXT, so only "" is default there).
    """
    if a.is_default_initial_value and b.is_default_initial_value:
        return False
    return a.initial_value != b.initial_value
