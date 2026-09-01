"""Dialog for importing address data from CSV with merge options."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from pyclickplc.banks import MEMORY_TYPE_BASES
from pyclickplc.blocks import BlockRange, compute_all_block_ranges
from tksheet import Sheet, num2alpha

from ..data.data_source import CsvDataSource

if TYPE_CHECKING:
    from ..models.address_row import AddressRow


class BlockGroup:
    """Represents a group of addresses with the same block tag.

    Membership is an explicit list of indices rather than a span, because the
    "Untagged" group is not contiguous - tagged blocks sit between its rows.
    """

    def __init__(self, name: str, indices: list[int], rows: list[AddressRow]):
        """Initialize block group.

        Args:
            name: Block name (or "Untagged" for addresses without blocks)
            indices: Indices into rows that belong to this group
            rows: List of all AddressRow objects (reference to full list)
        """
        self.name = name
        self.indices = indices
        self._all_rows = rows  # Reference to full list

    @property
    def start_idx(self) -> int:
        """Index of the first row in this group (used for display ordering)."""
        return min(self.indices) if self.indices else 0

    @property
    def rows(self) -> list[AddressRow]:
        """Get the rows in this block."""
        return [self._all_rows[i] for i in self.indices]

    @property
    def count(self) -> int:
        """Get count of addresses in this block."""
        return len(self.indices)

    def __repr__(self) -> str:
        return f"BlockGroup({self.name}, {self.count} addresses)"


def detect_blocks_in_csv(rows: list[AddressRow]) -> list[BlockGroup]:
    """Detect block groups in CSV rows using proper block range detection.

    Args:
        rows: List of AddressRow objects from CSV

    Returns:
        List of BlockGroup objects (blocks + untagged)
    """
    # Use blocktag utility to compute all block ranges
    block_ranges: list[BlockRange] = compute_all_block_ranges(rows)

    blocks: list[BlockGroup] = []
    covered_indices = set()

    # Convert BlockRange objects to BlockGroup objects
    for block_range in block_ranges:
        block_indices = list(range(block_range.start_idx, block_range.end_idx + 1))
        covered_indices.update(block_indices)

        blocks.append(
            BlockGroup(
                name=block_range.name,
                indices=block_indices,
                rows=rows,
            )
        )

    # Find untagged addresses (not in any block range)
    untagged_indices = [i for i in range(len(rows)) if i not in covered_indices]

    # All untagged addresses form one group. They need not be contiguous, so the
    # group holds their exact indices and never covers a tagged block in between.
    if untagged_indices:
        blocks.append(
            BlockGroup(
                name="Untagged",
                indices=untagged_indices,
                rows=rows,
            )
        )

    return sorted(blocks, key=lambda b: b.start_idx)


# Column indices (no Enable column - using index checkboxes instead)
COL_BLOCK_NAME = 0
COL_COUNT = 1
COL_NICKNAME = 2
COL_COMMENT = 3
COL_FIRST_SCAN = 4

# Dropdown options
NICKNAME_OPTIONS = ["Overwrite", "Merge", "Skip"]
COMMENT_OPTIONS = ["Overwrite", "Append", "Block Tag", "Skip"]
# Initial value and retentive are imported together - see ImportService._apply_first_scan
FIRST_SCAN_OPTIONS = ["Overwrite", "Merge", "Skip"]


class ImportCsvDialog(tk.Toplevel):
    """Dialog for importing CSV data with merge options using tksheet.

    Shows a table with one row per block and dropdown columns for merge options.
    """

    def _populate_sheet(self) -> None:
        """Populate the sheet with block data and setup dropdowns."""
        # Build data rows
        data = []
        for block in self.all_blocks:
            data.append(
                [
                    block.name,
                    str(block.count),
                    "Overwrite",  # Default for Nickname
                    "Overwrite",  # Default for Comment
                    "Merge",  # Default for First Scan
                ]
            )

        self.sheet.set_sheet_data(data)

        # Create index checkboxes (in row headers) - all enabled by default
        for row_idx in range(len(self.all_blocks)):
            self.sheet.create_index_checkbox(r=row_idx, checked=True)

        # Setup dropdowns for merge option columns using column letters
        # Nickname column
        self.sheet.dropdown(
            num2alpha(COL_NICKNAME),
            values=NICKNAME_OPTIONS,
            set_value="Overwrite",
        )

        # Comment column
        self.sheet.dropdown(
            num2alpha(COL_COMMENT),
            values=COMMENT_OPTIONS,
            set_value="Overwrite",
        )

        # First Scan column (initial value + retentive, imported as a pair)
        self.sheet.dropdown(
            num2alpha(COL_FIRST_SCAN),
            values=FIRST_SCAN_OPTIONS,
            set_value="Merge",
        )

        # Disable editing for Block Name and Count columns
        self.sheet.readonly_columns(columns=[COL_BLOCK_NAME, COL_COUNT])

    def _load_csv(self) -> None:
        """Load CSV file and detect blocks."""
        if not self.csv_path:
            return

        try:
            # Load CSV using CsvDataSource
            csv_source = CsvDataSource(str(self.csv_path))
            address_dict = csv_source.load_all_addresses()
            rows = list(address_dict.values())

            # Sort rows by memory type and address for consistent block detection
            rows.sort(key=lambda r: (MEMORY_TYPE_BASES.get(r.memory_type, 0xFFFFFFFF), r.address))

            # Detect blocks
            self.all_blocks = detect_blocks_in_csv(rows)

            # Update UI
            self._populate_sheet()

            # Enable import button
            self.import_btn.configure(state="normal")

        except Exception as e:
            messagebox.showerror(
                "Load Error",
                f"Failed to load CSV file:\n{e}",
                parent=self,
            )

    def _on_browse(self) -> None:
        """Handle browse button click."""
        file_path = filedialog.askopenfilename(
            parent=self,
            title="Select CSV file to import",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )

        if not file_path:
            return

        self.csv_path = Path(file_path)
        self.file_label.configure(text=str(self.csv_path), foreground="black")

        # Load and analyze the CSV
        self._load_csv()

    def _on_select_all(self) -> None:
        """Select all blocks (check all index checkboxes)."""
        for row in range(len(self.all_blocks)):
            self.sheet.click_index_checkbox(r=row, checked=True)
        self.sheet.refresh(redraw_header=False)

    def _on_deselect_all(self) -> None:
        """Deselect all blocks (uncheck all index checkboxes)."""
        for row in range(len(self.all_blocks)):
            self.sheet.click_index_checkbox(r=row, checked=False)
        self.sheet.refresh(redraw_header=False)

    def _on_import(self) -> None:
        """Handle import button click."""
        if not self.csv_path or not self.all_blocks:
            return

        # Get selected blocks and their options
        selected_blocks = []
        import_options_per_block = {}

        # Use yield_sheet_rows to get boolean checkbox states
        # get_index=True: Includes the index checkbox data
        # get_index_displayed=False: Returns the boolean True/False instead of text
        for row_idx, row_data in enumerate(
            self.sheet.yield_sheet_rows(get_index=True, get_index_displayed=False)
        ):
            is_checked = row_data[0]  # This is the boolean state of the index checkbox

            if not is_checked:
                continue

            # Because the index is the first element, the table columns are shifted by 1
            # Example: row_data[1] is the first data column (Block Name)
            block = self.all_blocks[row_idx]
            selected_blocks.append(block)

            # Keyed by block identity, not name - a CSV may reuse a block name
            # Retrieve merge options using the +1 offset
            import_options_per_block[id(block)] = {
                "nickname": row_data[COL_NICKNAME + 1],
                "comment": row_data[COL_COMMENT + 1],
                "first_scan": row_data[COL_FIRST_SCAN + 1],
            }

        if not selected_blocks:
            messagebox.showwarning(
                "No Blocks Selected",
                "Please select at least one block to import.",
                parent=self,
            )
            return

        # Store result
        self.result = (self.csv_path, selected_blocks, import_options_per_block)
        self.destroy()

    def _on_cancel(self) -> None:
        """Handle cancel button click."""
        self.result = None
        self.destroy()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(
            main_frame,
            text="Import Address Data from CSV",
            font=("TkDefaultFont", 10, "bold"),
        )
        title_label.pack(pady=(0, 10))

        # File selection
        file_frame = ttk.Frame(main_frame)
        file_frame.pack(fill=tk.X, pady=(0, 10))

        self.file_label = ttk.Label(file_frame, text="No file selected", foreground="gray")
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(
            file_frame,
            text="Browse...",
            command=self._on_browse,
            width=12,
        ).pack(side=tk.RIGHT)

        # Instruction text
        instruction_text = "Select blocks to import and configure merge behavior for each field:"
        ttk.Label(main_frame, text=instruction_text, foreground="gray").pack(pady=(0, 5))

        # tksheet table with border
        sheet_frame = tk.Frame(main_frame, relief=tk.SUNKEN, borderwidth=2)
        sheet_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.sheet = Sheet(
            sheet_frame,
            headers=[
                "Block Name",
                "Count",
                "Nickname",
                "Comment",
                "First Scan",
            ],
            height=400,
            width=850,
        )
        self.sheet.enable_bindings()
        self.sheet.pack(fill=tk.BOTH, expand=True)

        # Set column widths
        self.sheet.column_width(column=COL_BLOCK_NAME, width=200)
        self.sheet.column_width(column=COL_COUNT, width=60)
        self.sheet.column_width(column=COL_NICKNAME, width=100)
        self.sheet.column_width(column=COL_COMMENT, width=120)
        self.sheet.column_width(column=COL_FIRST_SCAN, width=100)

        # Placeholder row
        self.sheet.set_sheet_data(
            [
                [
                    "(Load a CSV file to see blocks)",
                    "",
                    "",
                    "",
                    "",
                ]
            ]
        )

        # Column options help text (below table)
        help_text = (
            "Column Options:\n"
            "  Nickname:   Overwrite = Replace existing | Merge = Only if empty\n"
            "  Comment:    Overwrite | Append | Block Tag = Update tag only\n"
            "  First Scan: Initial Value + Retentive, imported together.\n"
            "              Retentive addresses power up with their retained value, so an\n"
            "              initial value only applies when Retentive is off - importing one\n"
            "              without the other silently changes first-scan behavior.\n"
            "              Overwrite = Take both from CSV | Merge = Only if both are default"
        )
        help_label = ttk.Label(
            main_frame, text=help_text, foreground="gray", font=("TkDefaultFont", 8)
        )
        help_label.pack(pady=(5, 10))

        # Bulk selection buttons (centered)
        button_frame1 = ttk.Frame(main_frame)
        button_frame1.pack(pady=(0, 10))

        ttk.Button(
            button_frame1,
            text="Select All",
            command=self._on_select_all,
            width=12,
        ).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(
            button_frame1,
            text="Deselect All",
            command=self._on_deselect_all,
            width=12,
        ).pack(side=tk.LEFT)

        # Import/Cancel buttons (centered)
        button_frame2 = ttk.Frame(main_frame)
        button_frame2.pack()

        self.import_btn = ttk.Button(
            button_frame2,
            text="📥 Import",
            command=self._on_import,
            width=12,
            state="disabled",
        )
        self.import_btn.pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(
            button_frame2,
            text="Cancel",
            command=self._on_cancel,
            width=12,
        ).pack(side=tk.LEFT)

    def __init__(self, parent: tk.Widget):
        """Initialize the import dialog.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.title("Import from CSV - Merge Options")
        self.transient(parent)
        self.grab_set()
        self.geometry("900x750")

        # Result: (file_path, selected_blocks, import_options)
        self.result: tuple[Path, list[BlockGroup], dict] | None = None

        # Data
        self.csv_path: Path | None = None
        self.all_blocks: list[BlockGroup] = []

        self._create_widgets()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
