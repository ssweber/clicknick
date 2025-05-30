import re
import tkinter as tk
from tkinter import ttk

from .nickname_combobox import NicknameCombobox
from .shared_ahk import AHK
from .window_mapping import DATA_TYPES


class Overlay(tk.Toplevel):
    """Overlay for nickname selection."""

    def _input_current_text(self):
        """Input whatever is currently in the combobox."""
        current_text = self.combobox.get().strip()
        if self.combobox.selection_callback:
            self.combobox.selection_callback(current_text)

    def _get_search_text(self):
        """Extract the actual search text, accounting for any selection"""
        current_text = self.combobox.get()
        if self.combobox.selection_present():
            sel_start = self.combobox.index("sel.first")
            return current_text[:sel_start]
        else:
            return current_text

    def _input_search_text(self):
        """Input only user-entered search text in the combobox."""
        current_text = self._get_search_text()
        if self.combobox.selection_callback:
            self.combobox.selection_callback(current_text)

    def _on_tab(self, event):
        """Handle tab key to input current text before withdrawing."""

        shift_tab = event.state & 0x1

        if not shift_tab:
            self._input_current_text()
            self._processing_selection = True
        self.withdraw()

    def _on_focus_out(self, event):
        """Handle focus-out event to input current text and withdraw the popup."""
        try:
            # Get the widget that now has focus
            focused_widget = self.focus_get()

            # If focus moved to one of your widgets, don't withdraw
            if focused_widget and (
                focused_widget == self or focused_widget.winfo_toplevel() == self.winfo_toplevel()
            ):
                return

            # Input current text before withdrawing
            if not self._processing_selection:
                self._input_search_text()

            # Small delay to allow for potential click actions to complete
            self._debounce_retrigger = True

            # Set new after calls and store their IDs
            self.focus_out_after_id = self.after(100, self.withdraw)
            self.debounce_after_id = self.after(
                1000, lambda: setattr(self, "_debounce_retrigger", False)
            )

        except KeyError:
            # This catches the 'popdown' KeyError that occurs when the combobox dropdown is involved
            pass
        except Exception as e:
            print(f"Focus out error: {e}")

    def _insert_text_to_field(self, text):
        """Insert the string into the current field using AHK."""
        if not self.target_window_id or not self.target_edit_control:
            return

        try:
            # Use AHK to set the text in the field
            AHK.f(
                "ControlSetText",
                self.target_edit_control,
                text,
                f"ahk_id {self.target_window_id}",
            )

            # Set the text to the end (like you typed it)
            AHK.call("ControlEnd", self.target_edit_control, f"ahk_id {self.target_window_id}")
            AHK.call("WinActivate", f"ahk_id {self.target_window_id}")
        except Exception as e:
            print(f"Error inserting text: {e}")

    def _on_nickname_selected(self, nickname):
        """
        Handle nickname selection.

        If the nickname corresponds to an address, insert that address.
        Otherwise, pass on the text.
        """
        self._processing_selection = True

        # First check if it's a known nickname
        address = self.nickname_manager.get_address_for_nickname(nickname)
        if address:
            self._insert_text_to_field(address)
        else:
            self._insert_text_to_field(nickname)

    def __init__(self, root, nickname_manager):
        super().__init__(root)
        self.title("ClickNickOverlay")
        self.overrideredirect(True)  # No window decorations
        self.attributes("-topmost", True)  # Stay on top
        self.withdraw()  # Hide initially

        # Create the combobox
        # Configure style for wider dropdown
        style = ttk.Style()
        style.configure("Wider.TCombobox", postoffset=(0, 0, 90, 0))  # last value extends width
        self.combobox = NicknameCombobox(self, width=30, style="Wider.TCombobox")
        self.combobox.pack(padx=2, pady=2)
        self.combobox.set_selection_callback(self._on_nickname_selected)
        self.combobox.set_text_input_callback(self.on_text_input)

        # Store dependencies - nickname_manager already has settings
        self.nickname_manager = nickname_manager

        # Target window information
        self.target_window_id = None
        self.target_window_class = None
        self.target_edit_control = None
        self.allowed_types = []

        self._debounce_retrigger = False
        self._processing_selection = False

        # Setup focus bindings
        self.bind("<FocusOut>", self._on_focus_out)
        self.combobox.bind("<FocusOut>", self._on_focus_out)
        self.bind("<KeyPress-Tab>", self._on_tab)

        # Initialize after IDs
        self.focus_out_after_id = None
        self.debounce_after_id = None

    def _is_possible_address_or_number(self, search_text):
        """
        Check if the input is a valid address or a numeric value.

        Returns True if:
        1. Input is a prefix of any valid prefix (e.g., "C" or "CT" for prefix "CTD")
        2. Input is a complete prefix optionally followed by digits (e.g., "CTD" or "CTD123")
        3. Input is numeric (int or float)

        Args:
            input_text (str): The input to check

        Returns:
            bool: True if the input is a valid address or numeric value, False otherwise
        """
        if not search_text:
            return True

        search_text = search_text.lower().strip()

        # Check if the input is just numbers or numbers with a decimal point
        if re.match(r"^[0-9]+(\.[0-9]*)?$", search_text):
            return True

        # Check against all prefixes
        for prefix in DATA_TYPES.keys():
            prefix = prefix.lower()

            # Case 1: Input is a prefix of the full prefix (e.g., "C" or "CT" for "CTD")
            if prefix.startswith(search_text):
                return True

            # Case 2: Input starts with the complete prefix and remainder is digits
            if (
                search_text.startswith(prefix)
                and len(search_text) > len(prefix)
                and search_text[len(prefix) :].isdigit()
            ):
                return True

            # Case 3: Input is exactly the prefix
            if search_text == prefix:
                return True

        return False

    def _filter_items(self):
        """Filter and return items based on input text"""
        if not self.allowed_types:
            return []

        # Extract only the un-selected (user-typed) text
        search_text = self._get_search_text()

        # Use nickname manager's built-in filtering with app settings
        return self.nickname_manager.get_filtered_nicknames(self.allowed_types, search_text)

    def _should_show_dropdown(self):
        """Determine if dropdown should be shown based on input text"""
        search_text = self._get_search_text()
        return not self._is_possible_address_or_number(search_text)

    def on_text_input(self):
        """
        Process text input, update dropdown content, and determine visibility.
        Returns: Whether the dropdown should be displayed.
        """
        # Do filtering logic and update dropdown
        filtered_items = self._filter_items()
        self.combobox.update_values(filtered_items)

        # Determine visibility and return
        if not filtered_items:
            return False
        return self._should_show_dropdown()

    def set_target_window(self, window_id, window_class, edit_control):
        """Set the target window information."""
        self.target_window_id = window_id
        self.target_window_class = window_class
        self.target_edit_control = edit_control

    def is_active(self):
        """Check if the popup is currently active and managing a window."""
        return self.target_window_id is not None and self.winfo_viewable()

    def _get_control_position(self) -> tuple[int, int, int, int] | None:
        """
        Get the screen position of the target input field.

        Returns:
            Tuple of (x, y, width, height) or None if position cannot be determined
        """
        try:
            if not self.target_window_id or not self.target_edit_control:
                return None

            # Get window position
            window_pos = AHK.f("WinGetPos", f"ahk_id {self.target_window_id}")
            if not window_pos:
                print("Could not determine window position")
                return None

            # Parse positions
            win_x, win_y, win_width, win_height = map(int, window_pos.split(","))

            # Get control position
            control_pos = AHK.f(
                "ControlGetPos",
                self.target_edit_control,
                f"ahk_id {self.target_window_id}",
            )
            if not control_pos:
                print("Could not determine control position")
                return None

            # Parse control position
            ctrl_x, ctrl_y, ctrl_width, ctrl_height = map(int, control_pos.split(","))

            # Calculate screen coordinates
            screen_x = win_x + ctrl_x
            screen_y = win_y + ctrl_y

            return (screen_x, screen_y, ctrl_width, ctrl_height)

        except Exception as e:
            print(f"Error getting control position: {e}")
            return None

    def position_near_edit_control(self) -> bool:
        """
        Position the combobox directly over the currently focused edit control.

        Returns:
            bool: True if positioning was successful
        """
        try:
            # Get position of the target control
            position = self._get_control_position()
            if not position:
                self.withdraw()
                return False

            # Extract position components
            x, y, width, height = position

            # Reset combobox state
            self.combobox._reset()

            # Configure combobox width to match the control width
            # Convert pixel width to character width (approximate conversion)
            char_width = width // 7  # Approximate character width in pixels
            self.combobox.configure(width=char_width)

            # Position window exactly over the control
            self.geometry(f"{width}x{self.combobox.winfo_reqheight()}+{x}+{y}")
            self.update_idletasks()  # Process pending geometry-related events

            # More robust focus handling
            # deactivate the ClickPLC window
            AHK.call("WinActivate", "ahk_class Shell_TrayWnd")

            self.deiconify()
            AHK.call("WinActivate", "ClickNickOverlay")
            self.update()
            self.combobox.focus_set()  # Then force focus on the combobox

            return True

        except Exception as e:
            print(f"Error positioning combobox: {e}")
            self.withdraw()
            return False

    def show_combobox(self, allowed_types):
        """Show the combobox popup with filtered nicknames."""
        if not self.combobox or not allowed_types or self._debounce_retrigger:
            return

        self._processing_selection = False

        # Store allowed types for text change handling
        self.allowed_types = allowed_types

        # Get initial nicknames using the nickname manager's built-in filtering
        nicknames = self.nickname_manager.get_filtered_nicknames(allowed_types, "")
        self.combobox.update_values(nicknames)

        # Only show if positioning is successful
        if not self.position_near_edit_control():
            return

    def withdraw(self):
        """Override withdraw to cancel any pending after calls"""

        # Cancel any pending after calls, safely checking if attributes exist
        if hasattr(self, "focus_out_after_id") and self.focus_out_after_id:
            self.after_cancel(self.focus_out_after_id)
            self.focus_out_after_id = None

        if hasattr(self, "debounce_after_id") and self.debounce_after_id:
            self.after_cancel(self.debounce_after_id)
            self.debounce_after_id = None

        # Call the parent class's withdraw method
        super().withdraw()
