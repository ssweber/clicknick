import tkinter as tk
from tkinter import ttk

from .floating_tooltip import FloatingTooltip
from .nickname_combobox import NicknameCombobox
from .shared_ahk import AHK


class Overlay(tk.Toplevel):
    """Overlay for nickname selection."""

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

    def _provide_filtered_data(self, search_text: str) -> tuple[list[str], bool]:
        """
        Data provider function for the combobox.

        Args:
            search_text: The current search text from the combobox

        Returns:
            filtered_values
        """
        if not self.allowed_types:
            return []

        # Get filtered nicknames using the nickname manager
        filtered_items = self.nickname_manager.get_filtered_nicknames(
            self.allowed_types, search_text
        )

        return filtered_items

    def _on_nickname_navigation(self, nickname):
        """Handle navigation through nickname items to show details in tooltip."""
        # Check if tooltips are enabled in settings
        if not (
            hasattr(self.nickname_manager, "settings")
            and self.nickname_manager.settings
            and self.nickname_manager.settings.show_info_tooltip
        ):
            self.tooltip.hide_tooltip()
            return

        if nickname and self.nickname_manager:
            details = self.nickname_manager.get_nickname_details(nickname)
            if details:
                # Get position above the combobox
                x = self.winfo_rootx()
                y = self.winfo_rooty()
                self.tooltip.show_tooltip(details, x, y)
            else:
                self.tooltip.hide_tooltip()
        else:
            self.tooltip.hide_tooltip()

    def _on_nickname_selected(self, nickname):
        """
        Handle nickname selection.

        If the nickname corresponds to an address, insert that address.
        Otherwise, pass on the text.
        """
        self.combobox.finalizing = True

        # First check if it's a known nickname
        address = self.nickname_manager.get_address_for_nickname(nickname)
        if address:
            self._insert_text_to_field(address)
        else:
            self._insert_text_to_field(nickname)

    def _setup_combobox(self):
        """Create the combobox and configure"""
        # Configure style for wider dropdown
        style = ttk.Style()
        style.configure("Wider.TCombobox", postoffset=(0, 0, 90, 0))  # last value extends width
        self.combobox = NicknameCombobox(self, width=30, style="Wider.TCombobox")
        self.combobox.pack(padx=2, pady=2)

        # provide functions
        self.combobox.set_data_provider(self._provide_filtered_data)
        self.combobox.set_item_navigation_callback(self._on_nickname_navigation)
        self.combobox.set_selection_callback(self._on_nickname_selected)

    def _on_focus_out(self, event):
        """Handle focus-out event to input current text and withdraw the popup."""
        try:
            # Get the widget that now has focus
            focused_widget = self.focus_get()

            # If focus moved to one of your widgets or the tooltip, don't withdraw
            if focused_widget and (
                focused_widget == self
                or focused_widget.winfo_toplevel() == self.winfo_toplevel()
                or focused_widget.winfo_toplevel() == self.tooltip
            ):
                return

            # Input current text before withdrawing
            if not self.combobox.finalizing:
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

    def _setup_bindings(self):
        # Setup focus bindings
        self.bind("<FocusOut>", self._on_focus_out)
        self.combobox.bind("<FocusOut>", self._on_focus_out)

    def __init__(self, root, nickname_manager):
        super().__init__(root)
        self.title("ClickNickOverlay")
        self.overrideredirect(True)  # No window decorations
        self.attributes("-topmost", True)  # Stay on top
        self.withdraw()  # Hide initially

        self._setup_combobox()

        # Store dependencies - nickname_manager already has settings
        self.nickname_manager = nickname_manager

        # Create floating tooltip
        self.tooltip = FloatingTooltip(self)

        # Target window information
        self.target_window_id = None
        self.target_window_class = None
        self.target_edit_control = None
        self.allowed_types = []

        self._debounce_retrigger = False
        self.combobox.finalizing = False

        self._setup_bindings()

        # Initialize after IDs
        self.focus_out_after_id = None
        self.debounce_after_id = None

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

            # Quick fix: add buffer for Edit controls
            if self.target_edit_control.startswith("Edit"):
                return (screen_x - 5, screen_y - 5, ctrl_width + 28.5, ctrl_height + 10)

            return (screen_x, screen_y, ctrl_width, ctrl_height)

        except Exception as e:
            print(f"Error getting control position: {e}")
            return None

    def is_active(self):
        """Check if the popup is currently active and managing a window."""
        return self.target_window_id is not None and self.winfo_viewable()

    def set_target_window(self, window_id, window_class, edit_control):
        """Set the target window information."""
        self.target_window_id = window_id
        self.target_window_class = window_class
        self.target_edit_control = edit_control

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

            # Reset combobox state and hide tooltip
            self.combobox.reset()
            self.tooltip.hide_tooltip()

            # Configure combobox width to match the control width
            # Convert pixel width to character width (approximate conversion)
            char_width = int(width // 7)  # Approximate character width in pixels
            self.combobox.configure(width=char_width)

            # Position window exactly over the control
            self.geometry(f"{int(width)}x{height}+{x}+{y}")
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

        self.combobox.finalizing = False

        # Store allowed types for the data provider
        self.allowed_types = allowed_types

        # Get initial nicknames for empty search
        initial_nicknames = self._provide_filtered_data("")
        self.combobox.update_values(initial_nicknames)

        # Only show if positioning is successful
        if not self.position_near_edit_control():
            return

    def withdraw(self):
        """Override withdraw to cancel any pending after calls and hide tooltip"""
        # Hide the tooltip
        if hasattr(self, "tooltip"):
            self.tooltip.hide_tooltip()

        # Cancel any pending after calls, safely checking if attributes exist
        if hasattr(self, "focus_out_after_id") and self.focus_out_after_id:
            self.after_cancel(self.focus_out_after_id)
            self.focus_out_after_id = None

        if hasattr(self, "debounce_after_id") and self.debounce_after_id:
            self.after_cancel(self.debounce_after_id)
            self.debounce_after_id = None

        # Call the parent class's withdraw method
        super().withdraw()
