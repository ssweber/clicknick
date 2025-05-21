import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from .combobox_autocomplete import PrefixAutocomplete
from .combobox_filter import ContainsFilter, FuzzyFilter, NoneFilter, PrefixFilter
from .shared_ahk import AHK


class NicknamePopup(tk.Toplevel):
    """Popup window for nickname selection."""

    def __init__(self, root, nickname_mananger, search_var=None, fuzzy_threshold_var=None):
        super().__init__(root)
        self.title("ClickNick Popup")
        self.overrideredirect(True)  # No window decorations
        self.attributes("-topmost", True)  # Stay on top
        self.withdraw()  # Hide initially

        # Create the combobox
        self.combobox = NicknameCombobox(self, width=30)
        self.combobox.pack(padx=2, pady=2)
        self.combobox.set_selection_callback(self._on_nickname_selected)

        # Set the search variable if provided
        if search_var:
            self.combobox.set_search_var(search_var)

        # Set the fuzzy threshold variable if provided
        if fuzzy_threshold_var:
            self.combobox.set_fuzzy_threshold_var(fuzzy_threshold_var)

        # Store dependencies
        self.nickname_manager = nickname_mananger

        # Target window information
        self.target_window_id = None
        self.target_window_class = None
        self.target_edit_control = None

        self._debounce_retrigger = False

        # Setup focus bindings
        self.bind("<FocusOut>", self._on_focus_out)
        self.combobox.bind("<FocusOut>", self._on_focus_out)

    def _on_focus_out(self, event):
        """Handle focus-out event to withdraw the popup."""
        try:
            # Get the widget that now has focus
            focused_widget = self.focus_get()

            # If focus moved to one of your widgets, don't withdraw
            if focused_widget and (
                focused_widget == self or focused_widget.winfo_toplevel() == self.winfo_toplevel()
            ):
                return

            self._debounce_retrigger = True
            # Small delay to allow for potential click actions to complete

            self.after(100, self.withdraw)
            self.after(1000, lambda: setattr(self, "_debounce_retrigger", False))
        except KeyError:
            # This catches the 'popdown' KeyError that occurs when the combobox dropdown is involved
            pass
        except Exception as e:
            print(f"Focus out error: {e}")

    def set_target_window(self, window_id, window_class, edit_control):
        """Set the target window information."""
        self.target_window_id = window_id
        self.target_window_class = window_class
        self.target_edit_control = edit_control

    def is_active(self):
        """Check if the popup is currently active and managing a window."""
        return self.target_window_id is not None and self.winfo_viewable()

    def position_near_edit_control(self) -> bool:
        """
        Position the combobox near the currently focused edit control.

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

            # Position and show combobox
            self.geometry(f"+{x}+{y + height}")
            self.deiconify()
            self.update()  # Process any pending events
            
            AHK.call("WinActivate", "ahk_class Shell_TrayWnd")
            
            self.combobox.focus_force()

            return True

        except Exception as e:
            print(f"Error positioning combobox: {e}")
            self.withdraw()
            return False

    def _reset_debounce(self):
        """Reset the focus-out debounce flag."""
        self._debounce_focusout = False

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

    def show_combobox(self, allowed_types):
        """Show the combobox popup with filtered nicknames."""
        if not self.combobox or not allowed_types or self._debounce_retrigger:
            return

        # Update the combobox values with filtered nicknames
        nicknames = self.nickname_manager.get_nicknames_for_combobox(allowed_types)
        self.combobox.update_values(nicknames)

        # Only show if positioning is successful
        if not self.position_near_edit_control():
            return

    def _on_nickname_selected(self, nickname):
        """
        Handle nickname selection.

        If the nickname corresponds to an address, insert that address.
        If the nickname is a valid address or numeric value, pass it along directly.
        """
        # First check if it's a known nickname
        address = self.nickname_manager.get_address_for_nickname(nickname)

        if address:
            self._insert_address_to_field(address)
        elif self.nickname_manager.is_valid_address_or_numeric(nickname):
            self._insert_address_to_field(nickname)

    def _insert_address_to_field(self, address):
        """Insert the address into the current field using AHK."""
        if not self.target_window_id or not self.target_edit_control:
            return

        try:
            # Use AHK to set the text in the field
            AHK.f(
                "ControlSetText",
                self.target_edit_control,
                address,
                f"ahk_id {self.target_window_id}",
            )
        except Exception as e:
            print(f"Error inserting address: {e}")


class NicknameCombobox(ttk.Combobox):
    """Enhanced combobox for nickname selection with autocomplete and positioning."""

    def __init__(self, parent, **kwargs):
        # Extract values before passing kwargs to parent
        self.values_list = kwargs.pop("values", [])

        # Initialize parent with valid ttk.Combobox options only
        super().__init__(parent, **kwargs)

        # Store dependencies
        self.selection_callback = None

        # Setup search strategy with default value
        self.search_var = tk.StringVar(value="none")
        self.fuzzy_threshold_var = tk.IntVar(value=60)  # Default threshold

        # Initialize filters
        self._init_filters()

        # Configure combobox
        self["values"] = self.values_list

        # Initialize autocomplete
        self._autocomplete = PrefixAutocomplete(self)
        self._autocomplete.set_completion_list(self.values_list)

        # Set up postcommand to filter results
        self.configure(postcommand=self._filter_results)

        # Bind events
        self.bind("<<ComboboxSelected>>", self._on_selection)
        self.bind("<KeyRelease>", self._handle_keyrelease)

    def set_selection_callback(self, callback: Callable[[str], None]) -> None:
        """Set the callback function for when a selection is made."""
        self.selection_callback = callback

    def _init_filters(self):
        """Initialize the search strategies"""
        self.strategies = {
            "none": NoneFilter(),
            "prefix": PrefixFilter(),
            "contains": ContainsFilter(),
            "fuzzy": FuzzyFilter(),
        }

    def set_search_var(self, search_var):
        """Set the variable that controls the search strategy"""
        self.search_var = search_var

    def update_values(self, values: list[str]) -> None:
        """Update the combobox values and autocomplete list."""
        self.values_list = values
        self["values"] = values
        self._autocomplete.set_completion_list(values)

    def set_fuzzy_threshold_var(self, fuzzy_threshold_var):
        """Set the variable that controls the fuzzy threshold"""
        self.fuzzy_threshold_var = fuzzy_threshold_var

    def _filter_results(self):
        """Filter dropdown results based on current text and search strategy"""
        current_text = self.get()

        # If there's a selection, we only want the part before the selection
        if self.selection_present():
            sel_start = self.index("sel.first")
            current_text = current_text[:sel_start]

        # Get current search strategy
        strategy_name = self.search_var.get()
        strategy = self.strategies.get(strategy_name, self.strategies["none"])

        # Set fuzzy threshold if using fuzzy strategy
        if strategy_name == "fuzzy" and isinstance(strategy, FuzzyFilter):
            strategy.threshold = self.fuzzy_threshold_var.get()

        # Filter values using the selected strategy
        filtered_values = strategy.filter_matches(self.values_list, current_text)

        # Update dropdown list
        self["values"] = filtered_values

    def _reset(self) -> None:
        """Reset the combobox content and autocomplete state."""
        # Clear current text
        self.delete(0, tk.END)

        # Reset autocomplete state
        self._autocomplete.reset()

    def _hide_combobox(self) -> None:
        """Hide the combobox popup."""
        self.master.withdraw()

    def _handle_keyrelease(self, event) -> None:
        """Handle key release events for navigation and selection."""
        if event.keysym == "Escape":
            self._hide_combobox()
            return

        if event.keysym == "Return":
            self._finalize_selection()
            return

        # Delegate to autocomplete logic
        self._autocomplete.handle_keyrelease(event)

        # Update dropdown list based on current text
        self._filter_results()

    def _on_selection(self, event) -> None:
        """Handle combobox selection event."""
        self._finalize_selection()

    def _finalize_selection(self) -> None:
        """Process the selected item and notify via callback."""
        selected = self.get()
        if selected and self.selection_callback:
            self.selection_callback(selected)
        self.master.withdraw()
