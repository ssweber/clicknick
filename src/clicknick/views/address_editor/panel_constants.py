"""Shared constants for AddressPanel and related components."""

# Column indices for AddressPanel sheets
# Address is in row index, not a data column
COL_USED = 0
COL_NICKNAME = 1
COL_COMMENT = 2
COL_INIT_VALUE = 3
COL_RETENTIVE = 4

# Color constants for styling
COLOR_ERROR_BG = "#ffcccc"  # Light red for validation errors
COLOR_DIRTY_BG = "#ffffcc"  # Light yellow for unsaved changes
COLOR_NON_EDITABLE_BG = "#e0e0e0"  # Gray for non-editable cells
COLOR_NON_EDITABLE_FG = "#666666"  # Dark gray text for non-editable
COLOR_COMBINED_TYPE_ALT = "#f0f8ff"  # Light blue for TD/CTD alternating rows
COLOR_HIGHLIGHT_TEMP = "#90EE90"  # Light green for navigation highlight
