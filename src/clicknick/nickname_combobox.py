import re
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from .prefix_autocomplete import PrefixAutocomplete
from .window_mapping import DATA_TYPES


class ComboboxTCLManager:
    """Manages TCL setup for enhanced combobox focus behavior."""

    _tcl_setup_done = False

    @classmethod
    def _setup_tcl(cls, parent):
        """Setup TCL code to control focus behavior."""
        tk_instance = parent.tk
        tcl_code = """
        # Override combobox Post function to support keeping entry focus
        if {![info exists ttk::combobox::State(programmaticPost)]} {
            set ttk::combobox::State(programmaticPost) 0
        }
        
        if {![info exists ttk::combobox::OriginalPost]} {
            rename ttk::combobox::Post ttk::combobox::OriginalPost
        }
        
        proc ttk::combobox::Post {cb {keepEntryFocus 0}} {
            variable State
            set State(programmaticPost) $keepEntryFocus
            OriginalPost $cb
        }
        
        proc ttk::combobox::PostProgrammatic {cb} {
            Post $cb 1
        }
        
        # Control focus when dropdown appears
        bind ComboboxListbox <Map> {
            set programmatic_flag $ttk::combobox::State(programmaticPost)
            if {!$programmatic_flag} {
                focus %W
            } else {
                set cb [ttk::combobox::LBMaster %W]
                focus $cb
                set ttk::combobox::State(programmaticPost) 0
            }
        }
        """
        tk_instance.eval(tcl_code)

    @classmethod
    def setup_tcl_if_needed(cls, parent):
        """Setup TCL code once for dual focus behavior."""
        if not cls._tcl_setup_done:
            cls._setup_tcl(parent)
            cls._tcl_setup_done = True


class DropdownManager:
    """Manages dropdown operations for combobox."""

    def __init__(self, combobox):
        self.combobox = combobox
        self.original_selectbackground = None
        self.listbox_has_focus = False
        self._bindings_set = False

    def get_listbox_widget(self):
        """Get the listbox widget from the dropdown."""
        try:
            listbox_path = f"{self.combobox._w}.popdown.f.l"
            if self.combobox.tk.eval(f"winfo exists {listbox_path}") == "1":
                return listbox_path
            return None
        except tk.TclError:
            return None

    def get_highlighted_item(self):
        """Get the currently highlighted item in the dropdown."""
        listbox = self.get_listbox_widget()
        if listbox:
            try:
                # Get the active (highlighted) item index
                active_index = self.combobox.tk.call(listbox, "index", "active")
                if active_index >= 0:
                    # Get the text of the active item
                    return self.combobox.tk.call(listbox, "get", active_index)
            except tk.TclError:
                pass
        return None

    def is_dropdown_open(self):
        """Check if dropdown is open."""
        try:
            popdown_widget = f"{self.combobox._w}.popdown"
            exists = self.combobox.tk.eval(f"winfo exists {popdown_widget}")
            if exists == "1":
                return self.combobox.tk.eval(f"winfo viewable {popdown_widget}") == "1"
            return False
        except tk.TclError:
            return False

    def _set_focused_appearance(self):
        """Restore listbox selection colors to normal (focused state)."""
        listbox = self.get_listbox_widget()
        if listbox and self.original_selectbackground is not None:
            try:
                # Restore original colors
                self.combobox.tk.call(
                    listbox, "configure", "-selectbackground", self.original_selectbackground
                )
                self.combobox.tk.call(
                    listbox, "configure", "-selectforeground", self.original_selectforeground
                )
                self.listbox_has_focus = True
            except tk.TclError:
                pass

    def _set_unfocused_appearance(self):
        """Set listbox selection colors to a disabled/unfocused state."""
        listbox = self.get_listbox_widget()
        if listbox:
            try:
                # Store original colors if not already stored
                if self.original_selectbackground is None:
                    self.original_selectbackground = self.combobox.tk.call(
                        listbox, "cget", "-selectbackground"
                    )
                    self.original_selectforeground = self.combobox.tk.call(
                        listbox, "cget", "-selectforeground"
                    )

                # Use most reliable lookup with fallback
                try:
                    unfocused_bg = self.combobox.tk.eval("ttk::style lookup . -background disabled")
                    unfocused_fg = self.combobox.tk.eval("ttk::style lookup . -foreground disabled")
                except tk.TclError:
                    pass

                # If lookups failed, use fallbacks
                if not unfocused_bg:
                    unfocused_bg = "#d9d9d9"  # Light grey
                if not unfocused_fg:
                    unfocused_fg = "#717171"  # Muted dark grey

                # Set both background and foreground colors
                self.combobox.tk.call(listbox, "configure", "-selectbackground", unfocused_bg)
                self.combobox.tk.call(listbox, "configure", "-selectforeground", unfocused_fg)
                self.listbox_has_focus = False
            except tk.TclError:
                pass

    def _check_focus_state(self):
        """Check current focus state and update appearance accordingly."""
        listbox = self.get_listbox_widget()
        if listbox:
            try:
                current_focus = self.combobox.tk.call("focus")
                if current_focus != listbox:
                    self._set_unfocused_appearance()
            except tk.TclError:
                pass

    def _show_tooltip_for_current_item(self):
        """Show tooltip for the currently highlighted item."""
        if (
            hasattr(self.combobox, "item_navigation_callback")
            and self.combobox.item_navigation_callback
        ):
            highlighted_item = self.get_highlighted_item()
            if highlighted_item:
                self.combobox.item_navigation_callback(highlighted_item)

    def _hide_tooltip(self):
        """Hide the tooltip."""
        if (
            hasattr(self.combobox, "item_navigation_callback")
            and self.combobox.item_navigation_callback
        ):
            self.combobox.item_navigation_callback("")

    def _on_listbox_focus_in(self):
        """Handle listbox focus-in event."""
        self._set_focused_appearance()
        self._show_tooltip_for_current_item()

    def _on_listbox_focus_out(self):
        """Handle listbox focus-out event."""
        # Only set unfocused appearance if mouse is not over the listbox
        # This prevents flickering when clicking on items
        self.combobox.after_idle(self._check_focus_state)
        self._hide_tooltip()

    def _on_listbox_mouse_enter(self):
        """Handle mouse entering listbox."""
        self._set_focused_appearance()
        self._show_tooltip_for_current_item()

    def _check_mouse_outside_dropdown(self):
        """Check if mouse is actually outside the entire dropdown area."""
        try:
            # Get mouse position relative to the listbox
            listbox = self.get_listbox_widget()
            if not listbox:
                self._hide_tooltip()
                return

            # Get mouse coordinates
            mouse_x = self.combobox.winfo_pointerx()
            mouse_y = self.combobox.winfo_pointery()

            # Get listbox geometry
            listbox_x = self.combobox.tk.call("winfo", "rootx", listbox)
            listbox_y = self.combobox.tk.call("winfo", "rooty", listbox)
            listbox_width = self.combobox.tk.call("winfo", "width", listbox)
            listbox_height = self.combobox.tk.call("winfo", "height", listbox)

            # Check if mouse is outside the listbox area (including scrollbar)
            if (
                mouse_x < listbox_x
                or mouse_x > listbox_x + listbox_width
                or mouse_y < listbox_y
                or mouse_y > listbox_y + listbox_height
            ):
                # Check if listbox actually has keyboard focus
                current_focus = self.combobox.tk.call("focus")
                if current_focus != listbox:
                    self._set_unfocused_appearance()
                self._hide_tooltip()

        except tk.TclError:
            self._hide_tooltip()

    def _on_listbox_mouse_leave(self):
        """Handle mouse leaving listbox."""
        # Schedule a delayed check to see if mouse is really outside the dropdown area
        self.combobox.after(50, self._check_mouse_outside_dropdown)

    def _trigger_navigation_callback(self, navigation_callback):
        """Trigger the navigation callback with the currently highlighted item."""
        highlighted_item = self.get_highlighted_item()
        if highlighted_item:
            navigation_callback(highlighted_item)
        else:
            # Call with empty string to ensure tooltip is hidden when no item is highlighted
            navigation_callback("")

    def _on_listbox_navigation(self, navigation_callback):
        """Handle listbox navigation events."""
        # Use after_idle to ensure the selection has been updated
        self.combobox.after_idle(lambda: self._trigger_navigation_callback(navigation_callback))

    def _bind_listbox_navigation_events(self, navigation_callback):
        """Bind navigation events to the listbox to track highlighting changes."""
        listbox = self.get_listbox_widget()
        if listbox and navigation_callback:
            try:
                # Bind arrow key events
                self.combobox.tk.call(
                    "bind",
                    listbox,
                    "<KeyPress-Up>",
                    self.combobox.register(
                        lambda: self._on_listbox_navigation(navigation_callback)
                    ),
                )
                self.combobox.tk.call(
                    "bind",
                    listbox,
                    "<KeyPress-Down>",
                    self.combobox.register(
                        lambda: self._on_listbox_navigation(navigation_callback)
                    ),
                )
                # Bind mouse motion for hover
                self.combobox.tk.call(
                    "bind",
                    listbox,
                    "<Motion>",
                    self.combobox.register(
                        lambda: self._on_listbox_navigation(navigation_callback)
                    ),
                )
            except tk.TclError:
                pass

    def setup_listbox_bindings(self):
        """Set up event bindings for the listbox widget."""
        listbox = self.get_listbox_widget()
        if listbox and not self._bindings_set:
            try:
                # Existing focus bindings
                self.combobox.tk.call(
                    "bind", listbox, "<FocusIn>", self.combobox.register(self._on_listbox_focus_in)
                )
                self.combobox.tk.call(
                    "bind",
                    listbox,
                    "<FocusOut>",
                    self.combobox.register(self._on_listbox_focus_out),
                )
                self.combobox.tk.call(
                    "bind", listbox, "<Enter>", self.combobox.register(self._on_listbox_mouse_enter)
                )
                self.combobox.tk.call(
                    "bind", listbox, "<Leave>", self.combobox.register(self._on_listbox_mouse_leave)
                )

                # Also bind to the scrollbar if it exists
                scrollbar_path = f"{self.combobox._w}.popdown.f.sb"
                if self.combobox.tk.eval(f"winfo exists {scrollbar_path}") == "1":
                    self.combobox.tk.call(
                        "bind",
                        scrollbar_path,
                        "<Leave>",
                        self.combobox.register(self._on_listbox_mouse_leave),
                    )

                # Add navigation bindings if callback is set
                if (
                    hasattr(self.combobox, "item_navigation_callback")
                    and self.combobox.item_navigation_callback
                ):
                    self._bind_listbox_navigation_events(self.combobox.item_navigation_callback)

                self._bindings_set = True
            except tk.TclError:
                pass

    def open_dropdown_keep_focus(self):
        """Open dropdown while keeping focus on entry."""
        if not self.is_dropdown_open():
            self.combobox.tk.call("ttk::combobox::PostProgrammatic", self.combobox._w)
            # Set light grey background when opening with focus kept on entry
            self._set_unfocused_appearance()
            # Set up bindings after dropdown is open
            self.combobox.after_idle(self.setup_listbox_bindings)

    def open_dropdown_transfer_focus(self):
        """Open dropdown and transfer focus to listbox."""
        if not self.is_dropdown_open():
            self.combobox.event_generate("<Button-1>")
            # Set up bindings after dropdown is open
            self.combobox.after_idle(self.setup_listbox_bindings)

    def hide_dropdown(self):
        """Hide the combobox popup."""
        if self.is_dropdown_open():
            self.combobox.event_generate("<Button-1>")
            # Reset focus state when dropdown closes
            self.listbox_has_focus = False
            self._bindings_set = False  # Reset bindings flag

            # Close tooltip when dropdown closes
            if hasattr(self.combobox, "master") and hasattr(self.combobox.master, "tooltip"):
                self.combobox.master.tooltip.hide_tooltip()

    def transfer_focus_to_listbox(self, direction=None):
        """
        Transfer focus to dropdown listbox and optionally send up/down keystroke.

        Args:
            direction (str, optional): 'up' or 'down' to send corresponding keystroke
        """
        try:
            listbox = f"{self.combobox._w}.popdown.f.l"

            # Set up bindings first
            self.setup_listbox_bindings()

            # Restore normal appearance before transferring focus
            self._set_focused_appearance()

            self.combobox.tk.call("focus", listbox)

            # Check if anything is currently selected
            current_selection = self.combobox.tk.call(listbox, "curselection")

            if not current_selection:  # If nothing is selected
                selection_index = 0  # Select first item
                self.combobox.tk.call(listbox, "selection", "set", selection_index)
                self.combobox.tk.call(listbox, "activate", selection_index)
            elif direction:
                if direction.lower() == "up":
                    self.combobox.event_generate("<Up>", when="tail")
                elif direction.lower() == "down":
                    self.combobox.event_generate("<Down>", when="tail")

        except tk.TclError:
            pass

    def update_listbox_directly(self, filtered_values):
        """Directly update the listbox contents without closing/reopening dropdown."""
        listbox = self.get_listbox_widget()
        if listbox:
            try:
                self.combobox.tk.call(listbox, "delete", 0, "end")
                for value in filtered_values:
                    self.combobox.tk.call(listbox, "insert", "end", value)

                if filtered_values:
                    # Get current text in the entry widget
                    current_text = self.combobox.get()

                    # Clear any existing selection first
                    self.combobox.tk.call(listbox, "selection", "clear", 0, "end")

                    # Only set selection if current text is found in filtered values
                    try:
                        selection_index = filtered_values.index(current_text)
                        self.combobox.tk.call(listbox, "selection", "set", selection_index)
                        self.combobox.tk.call(listbox, "activate", selection_index)
                        self.combobox.tk.call(listbox, "see", selection_index)
                    except ValueError:
                        # Don't select anything if current text isn't found
                        pass

                # Maintain unfocused appearance if listbox doesn't have focus
                if not self.listbox_has_focus:
                    self._set_unfocused_appearance()

                # Set up bindings after updating (including navigation bindings)
                self.setup_listbox_bindings()

            except tk.TclError:
                self.combobox["values"] = filtered_values


class ComboboxEventHandler:
    """Handles keyboard and selection events for combobox."""

    def __init__(self, combobox, dropdown_manager, autocomplete):
        self.combobox = combobox
        self.dropdown_manager = dropdown_manager
        self.autocomplete = autocomplete

    def _handle_data_provider_update(self, event):
        """Handle data provider updates and dropdown visibility."""
        if not (hasattr(self.combobox, "data_provider") and self.combobox.data_provider):
            return

        search_text = self.combobox.get_search_text()
        should_show_dropdown = not self.combobox.is_possible_address_or_literal(search_text)
        filtered_values = self.combobox.data_provider(search_text)

        # Update the combobox values
        self.combobox.update_values(filtered_values)

        # Determine dropdown visibility
        show_dropdown = (
            should_show_dropdown
            and filtered_values
            and ((event.char and event.char.isprintable()) or event.keysym == "BackSpace")
        )

        if show_dropdown:
            if not self.dropdown_manager.is_dropdown_open():
                self.dropdown_manager.open_dropdown_keep_focus()
        else:
            self.dropdown_manager.hide_dropdown()

    def _trigger_navigation_callback(self):
        """Trigger the navigation callback with current selection."""
        if self.combobox.item_navigation_callback:
            # Try to get highlighted item from dropdown first
            highlighted_item = self.dropdown_manager.get_highlighted_item()
            if highlighted_item:
                self.combobox.item_navigation_callback(highlighted_item)
            else:
                self.combobox.item_navigation_callback("")

    def _on_postcommand(self):
        """Handle postcommand event - set appearance and show tooltip."""
        self.dropdown_manager._set_focused_appearance()
        self.combobox.after_idle(self.dropdown_manager.setup_listbox_bindings)

    def _on_down_key(self, event):
        """Handle Down key - open dropdown and transfer focus to listbox."""
        if not self.dropdown_manager.is_dropdown_open():
            self.dropdown_manager.open_dropdown_transfer_focus()
            self._trigger_navigation_callback()
            return "break"

        if self.combobox.focus_get() == self.combobox:
            self.dropdown_manager.transfer_focus_to_listbox()
            self._trigger_navigation_callback()
            return "break"

    def _on_up_key(self, event):
        """Handle Up key - open dropdown and transfer focus to listbox."""
        if self.combobox.focus_get() == self.combobox:
            self.dropdown_manager.transfer_focus_to_listbox()
            self._trigger_navigation_callback()
            return "break"

    def _on_tab(self, event):
        """Handle tab key to input current text before withdrawing."""

        shift_tab = event.state & 0x1

        if not shift_tab:
            self.combobox.finalize_entry()

    def _handle_keyrelease(self, event):
        """Handle key release events for navigation and selection."""
        # Filter out shift key releases
        if event.keysym in ("Shift_L", "Shift_R"):
            return

        elif event.keysym == "Return":
            self.combobox.finalize_entry()
            return
        elif event.keysym == "Escape":
            self.combobox.master.withdraw()
            return

        self.autocomplete.handle_keyrelease(event)
        self._handle_data_provider_update(event)

    def _on_selection(self, event):
        """Handle combobox selection event."""
        self.combobox.finalize_selection()

    def bind_events(self):
        """Bind all events to the combobox."""
        self.combobox.configure(postcommand=self._on_postcommand)
        self.combobox.bind("<KeyPress-Down>", self._on_down_key)
        self.combobox.bind("<KeyPress-Up>", self._on_up_key)
        self.combobox.bind("<KeyPress-Tab>", self._on_tab)
        self.combobox.bind("<KeyRelease>", self._handle_keyrelease)
        self.combobox.bind("<<ComboboxSelected>>", self._on_selection)


class NicknameCombobox(ttk.Combobox):
    """Enhanced combobox for nickname selection with autocomplete and positioning."""

    def __init__(self, parent, **kwargs):
        # Setup TCL code once for dual focus behavior
        ComboboxTCLManager.setup_tcl_if_needed(parent)

        # Extract values before passing kwargs to parent
        self.values_list = kwargs.pop("values", [])

        # Initialize parent with valid ttk.Combobox options only
        super().__init__(parent, **kwargs)

        """Initialize all component managers."""
        self.data_provider = None
        self.keypress_callback = None
        self.selection_callback = None

        # Initialize managers
        self.dropdown_manager = DropdownManager(self)

        # Configure combobox
        self["values"] = self.values_list

        # Setup autocomplete
        self._autocomplete = PrefixAutocomplete(self)
        self._autocomplete.set_completion_list(self.values_list)

        # Setup event handling
        self.event_handler = ComboboxEventHandler(self, self.dropdown_manager, self._autocomplete)
        self.event_handler.bind_events()

        # Event handler will be initialized after autocomplete is set up
        self.item_navigation_callback = None

        self.finalizing = False

    # Public API methods

    def finalize_selection(self):
        """Process the selected item and notify via callback."""
        selected = self.get()
        if selected and self.selection_callback:
            self.selection_callback(selected)
        self.master.withdraw()

    def get_search_text(self):
        """Extract the actual search text, accounting for any selection"""
        current_text = self.get()
        if self.selection_present():
            sel_start = self.index("sel.first")
            return current_text[:sel_start]
        else:
            return current_text

    def is_possible_address_or_literal(self, search_text, strict=False):
        """
        Check if the input is a valid address or a supported literal value.

        Returns True if:
        1. Input is a prefix of any valid prefix (e.g., "C" or "CT" for prefix "CTD")
        2. Input is a complete prefix optionally followed by digits (e.g., "CTD" or "CTD123")
        3. Input starts with a single-quote
        4. Input is numeric (int or float)


        Args:
            input_text (str): The input to check
            strict: Only return True if a valid address or literal (eg C1, not just C)

        Returns:
            bool: True if the input is a valid address or numeric value, False otherwise
        """
        if not search_text:
            return True

        search_text = search_text.lower().strip()

        # Check if the input is just numbers or numbers with a decimal point
        if re.match(r"^[0-9]+(\.[0-9]*)?$", search_text):
            return True

        if search_text.startswith("'"):
            return True

        for prefix in DATA_TYPES.keys():
            prefix = prefix.lower()
            prefix_len = len(prefix)
            search_len = len(search_text)
            search_text_lower = search_text.lower()

            # Case 1: Input is a prefix of the full prefix (e.g., "C" or "CT" for "CTD")
            if not strict and prefix_len >= search_len and prefix[:search_len] == search_text:
                return True

            # Case 2: Input starts with the complete prefix and remainder is digits
            if (
                search_len > prefix_len
                and search_text_lower[:prefix_len] == prefix
                and search_text_lower[prefix_len:].isdigit()
            ):
                return True

        return False

    def finalize_entry(self):
        """Finalize the entry selection and notify the callback.

        Processes the current selection or input text in the following priority order:
        1. If the search text is a valid address/literal (strict check)
        2. If there's only one result
        3. If an item is selected but not focussed yet from the list
        4. Falls back to the raw input text if none of the above apply

        After processing, hides the master window.
        """
        self.finalizing = True
        search_text = self.get_search_text()
        values = self["values"]
        selection = self.current()
        selected = selection != -1

        if not self.selection_callback:
            return

        # Priority 1: Valid address/literal takes precedence
        if self.is_possible_address_or_literal(search_text, strict=True):
            self.selection_callback(search_text)

        # Priority 2: Single result with no explicit selection
        elif not selected and len(values) == 1:
            self.selection_callback(values[0])

        # Priority 3: Highlighted but not focussed from dropdown (since entry has focus)
        elif selected:
            self.selection_callback(values[selection])

        # Fallback: Use raw input text
        else:
            self.selection_callback(self.get())

        self.master.withdraw()

    def set_data_provider(self, provider_func: Callable[[str], tuple[list[str], bool]]) -> None:
        """
        Set the data provider function.

        Args:
            provider_func: Function that takes search text and returns filtered_values
        """
        self.data_provider = provider_func

    def set_item_navigation_callback(self, callback: Callable[[str], None]) -> None:
        """Set the callback function for when navigating through items."""
        self.item_navigation_callback = callback

    def set_selection_callback(self, callback: Callable[[str], None]) -> None:
        """Set the callback function for when a selection is made."""
        self.selection_callback = callback

    def reset(self):
        """Reset the combobox content and autocomplete state."""
        self.delete(0, tk.END)
        self._autocomplete.reset()

    def update_values(self, values: list[str]) -> None:
        """Update the combobox values and autocomplete list."""
        self.values_list = values
        self["values"] = values
        self._autocomplete.set_completion_list(values)

        # Update dropdown if open
        if self.dropdown_manager.is_dropdown_open():
            self.dropdown_manager.update_listbox_directly(values)
