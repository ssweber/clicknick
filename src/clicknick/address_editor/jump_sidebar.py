"""Address jump sidebar for the Address Editor.

Provides a sidebar with buttons for selecting memory types and address jumps.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class JumpButton(ttk.Frame):
    """A button for selecting a memory type, with optional submenu for address jumps."""

    def _on_jump_selected(self, address: int) -> None:
        """Handle jump address selection."""
        # Panel is already selected, just jump to address
        if self.on_jump:
            self.on_jump(self.type_name, address)

    def _build_nested_submenu(
        self,
        menu: tk.Menu,
        display_type: str,
        start_addr: int,
        end_addr: int,
    ) -> None:
        """Build submenu with 100-increment entries between start and end.

        Args:
            menu: Parent menu to add cascade to
            display_type: Type prefix for labels (e.g., "DS", "C")
            start_addr: Starting address for this submenu
            end_addr: End address (exclusive)
        """
        submenu = tk.Menu(menu, tearoff=0)

        # Add 100-increment addresses
        addr = start_addr
        while addr < end_addr:
            label = f"{display_type}{addr}"
            submenu.add_command(
                label=label,
                command=lambda a=addr: self._on_jump_selected(a),
            )
            addr += 100

        menu.add_cascade(label=f"{display_type}{start_addr}", menu=submenu)

    def _add_blocks_menu(self, menu: tk.Menu, display_type: str) -> None:
        """Add Blocks entry to menu if there are blocks defined.

        Args:
            menu: Menu to add blocks to
            display_type: Type prefix for labels (e.g., "DS", "C")
        """
        if not self.get_blocks_callback:
            return

        blocks = self.get_blocks_callback()
        if not blocks:
            return

        # Sort blocks by start address
        blocks = sorted(blocks, key=lambda x: x[0])

        menu.add_separator()

        def format_block_label(start_addr: int, end_addr: int | None, name: str) -> str:
            """Format a block label for display."""
            if end_addr is not None:
                return f"{name} ({display_type}{start_addr}-{display_type}{end_addr})"
            return f"{name} ({display_type}{start_addr})"

        if len(blocks) <= 5:
            # Add directly to menu
            menu.add_command(label="Blocks", state="disabled")
            for start_addr, end_addr, block_name, _bg_color in blocks:
                label = f"  {format_block_label(start_addr, end_addr, block_name)}"
                menu.add_command(
                    label=label,
                    command=lambda a=start_addr: self._on_jump_selected(a),
                )
        else:
            # Use submenu for >5 blocks
            blocks_submenu = tk.Menu(menu, tearoff=0)
            for start_addr, end_addr, block_name, _bg_color in blocks:
                label = format_block_label(start_addr, end_addr, block_name)
                blocks_submenu.add_command(
                    label=label,
                    command=lambda a=start_addr: self._on_jump_selected(a),
                )
            menu.add_cascade(label="Blocks", menu=blocks_submenu)

    def _show_jump_menu(self) -> None:
        """Show submenu for address jumps, including blocks."""
        menu = tk.Menu(self, tearoff=0)

        display_type = self.type_name.split("/")[0]

        # Types that use nested submenus with 100-increments
        nested_types = {"DS", "C"}

        if self.type_name in nested_types:
            for i, start_addr in enumerate(self.jump_addresses):
                # Determine end address (next jump point or end of range)
                if i + 1 < len(self.jump_addresses):
                    end_addr = self.jump_addresses[i + 1]
                else:
                    end_addr = start_addr + 500  # Last segment gets 500 more

                self._build_nested_submenu(menu, display_type, start_addr, end_addr)

            # Add blocks at the bottom
            self._add_blocks_menu(menu, display_type)
        else:
            # Standard handling for other types - flat list
            for addr in self.jump_addresses:
                label = f"{display_type}{addr}"
                menu.add_command(
                    label=label,
                    command=lambda a=addr: self._on_jump_selected(a),
                )

            # Add blocks at the bottom
            self._add_blocks_menu(menu, display_type)

        # Position menu next to the button
        x = self.button.winfo_rootx() + self.button.winfo_width()
        y = self.button.winfo_rooty()
        menu.post(x, y)

    def _on_click(self) -> None:
        """Handle main button click - select panel and show jump menu if applicable."""
        # Always select this type first
        self.on_select(self.type_name)

        # Show jump menu if this type has jumps (XD and YD don't)
        if self.jump_addresses or self.get_blocks_callback:
            self._show_jump_menu()

    def __init__(
        self,
        parent: tk.Widget,
        type_name: str,
        on_select: Callable,
        on_jump: Callable | None = None,
        jump_addresses: list[int] | None = None,
        get_blocks_callback: Callable | None = None,
    ):
        super().__init__(parent)

        self.type_name = type_name
        self.on_select = on_select
        self.on_jump = on_jump
        self.jump_addresses = jump_addresses or []
        self.get_blocks_callback = get_blocks_callback

        self._selected = False
        self._status_indicator = ""  # Current status indicator text

        # Main button - clicking opens panel AND shows jump menu (if applicable)
        self.button = ttk.Button(
            self,
            text=type_name,
            width=11,  # Full width since no arrow button
            command=self._on_click,
        )
        self.button.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _update_button_text(self) -> None:
        """Update button text to include status indicator."""
        if self._status_indicator:
            self.button.configure(text=f"{self.type_name} {self._status_indicator}")
        else:
            self.button.configure(text=self.type_name)

    def set_selected(self, selected: bool) -> None:
        """Set the visual selected state."""
        self._selected = selected
        # Use a different style or relief to show selection
        if selected:
            self.button.configure(style="Selected.TButton")
        else:
            self.button.configure(style="TButton")

    def update_status(self, modified_count: int, error_count: int) -> None:
        """Update the status indicator based on modified/error counts.

        Args:
            modified_count: Number of unsaved changes for this type
            error_count: Number of validation errors for this type
        """
        if error_count > 0:
            self._status_indicator = "⚠"
        elif modified_count > 0:
            self._status_indicator = "💾"
        else:
            self._status_indicator = ""
        self._update_button_text()


# Define panel types available in sidebar
SIDEBAR_TYPES = [
    "X",
    "Y",
    "C",
    "T/TD",  # Combined T + TD
    "CT/CTD",  # Combined CT + CTD
    "SC",
    "DS",
    "DD",
    "DH",
    "DF",
    "XD",
    "YD",
    "SD",
    "TXT",
]
# Types that show combined/interleaved data
COMBINED_TYPES = {
    "T/TD": ["T", "TD"],  # Timer panel shows T and TD interleaved
    "CT/CTD": ["CT", "CTD"],  # Counter panel shows CT and CTD interleaved
}
# Address range jump points for types with large ranges
ADDRESS_JUMPS = {
    "X": [1, 101, 201, 301, 401, 501, 601, 701, 801],
    "Y": [1, 101, 201, 301, 401, 501, 601, 701, 801],
    "C": [1, 501, 1001, 1501],
    "T/TD": [1, 101, 201, 301, 401],
    "CT/CTD": [1, 101, 201, 301, 401],
    "SC": [1, 101, 201, 301, 401, 501, 601, 701, 801, 901],
    "DS": [1, 501, 1001, 1501, 2001, 2501, 3001, 3501, 4001],
    "DD": [1, 101, 201, 301, 401, 501, 601, 701, 801, 901],
    "DH": [1, 101, 201, 301, 401],
    "DF": [1, 101, 201, 301, 401],
    "SD": [1, 101, 201, 301, 401, 501, 601, 701, 801, 901],
    "TXT": [1, 101, 201, 301, 401, 501, 601, 701, 801, 901],
}


class JumpSidebar(ttk.Frame):
    """Sidebar with type selection buttons."""

    def _get_blocks_for_type(self, type_name: str) -> list[tuple[int, int | None, str, str | None]]:
        """Get block definitions for a type from shared data.

        Args:
            type_name: The type name (may be combined like "T/TD")

        Returns:
            List of (start_addr, end_addr, block_name, bg_color) tuples.
            end_addr is None for self-closing (singular) blocks.
            bg_color is None if not specified.
        """
        if not self.shared_data:
            return []

        # Handle combined types (T/TD, CT/CTD)
        if type_name in COMBINED_TYPES:
            blocks = []
            for sub_type in COMBINED_TYPES[type_name]:
                blocks.extend(self.shared_data.get_block_addresses(sub_type))
            return sorted(blocks, key=lambda x: x[0])

        return self.shared_data.get_block_addresses(type_name)

    def _create_buttons(self) -> None:
        """Create all type buttons."""
        # Create a custom style for selected buttons
        style = ttk.Style()
        style.configure("Selected.TButton", background="#4a90d9")

        for type_name in SIDEBAR_TYPES:
            jump_addrs = ADDRESS_JUMPS.get(type_name)

            # Create callback for getting blocks for this type
            # Use default argument to capture type_name in closure
            def make_block_callback(t=type_name):
                return lambda: self._get_blocks_for_type(t)

            btn = JumpButton(
                self,
                type_name,
                on_select=self.on_type_select,
                on_jump=self.on_address_jump,
                jump_addresses=jump_addrs,
                get_blocks_callback=make_block_callback(),
            )
            btn.pack(fill=tk.X, padx=2, pady=1)
            self.buttons[type_name] = btn

    def __init__(
        self,
        parent: tk.Widget,
        on_type_select: Callable,
        on_address_jump: Callable,
        shared_data=None,
    ):
        super().__init__(parent, width=140)
        self.pack_propagate(False)  # Maintain fixed width

        self.on_type_select = on_type_select
        self.on_address_jump = on_address_jump
        self.shared_data = shared_data
        self.buttons: dict[str, JumpButton] = {}

        self._create_buttons()

    def set_selected(self, type_name: str) -> None:
        """Update which button appears selected."""
        for name, btn in self.buttons.items():
            btn.set_selected(name == type_name)

    def update_all_indicators(self) -> None:
        """Update status indicators on all buttons from shared data."""
        if not self.shared_data:
            return

        for type_name, btn in self.buttons.items():
            modified = self.shared_data.get_modified_count_for_type(type_name)
            errors = self.shared_data.get_error_count_for_type(type_name)
            btn.update_status(modified, errors)
