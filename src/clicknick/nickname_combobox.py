import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from .prefix_autocomplete import PrefixAutocomplete


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

    def _on_listbox_focus_in(self):
        """Handle listbox focus-in event."""
        self._set_focused_appearance()

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

    def _on_listbox_focus_out(self):
        """Handle listbox focus-out event."""
        # Only set unfocused appearance if mouse is not over the listbox
        # This prevents flickering when clicking on items
        self.combobox.after_idle(self._check_focus_state)

    def _on_listbox_mouse_enter(self):
        """Handle mouse entering listbox."""
        self._set_focused_appearance()

    def _on_listbox_mouse_leave(self):
        """Handle mouse leaving listbox."""
        # Check if listbox actually has keyboard focus
        listbox = self.get_listbox_widget()
        if listbox:
            try:
                current_focus = self.combobox.tk.call("focus")
                if current_focus != listbox:
                    self._set_unfocused_appearance()
            except tk.TclError:
                pass

    def _setup_listbox_bindings(self):
        """Set up event bindings for the listbox widget."""
        listbox = self.get_listbox_widget()
        if listbox and not self._bindings_set:
            try:
                # Bind focus-in events to restore focused appearance
                self.combobox.tk.call(
                    "bind", listbox, "<FocusIn>", self.combobox.register(self._on_listbox_focus_in)
                )

                # Bind focus-out events to set unfocused appearance
                self.combobox.tk.call(
                    "bind",
                    listbox,
                    "<FocusOut>",
                    self.combobox.register(self._on_listbox_focus_out),
                )

                # Also bind mouse enter/leave events for mouse-over behavior
                self.combobox.tk.call(
                    "bind", listbox, "<Enter>", self.combobox.register(self._on_listbox_mouse_enter)
                )

                self.combobox.tk.call(
                    "bind", listbox, "<Leave>", self.combobox.register(self._on_listbox_mouse_leave)
                )

                self._bindings_set = True
            except tk.TclError:
                pass

    def get_listbox_widget(self):
        """Get the listbox widget from the dropdown."""
        try:
            listbox_path = f"{self.combobox._w}.popdown.f.l"
            if self.combobox.tk.eval(f"winfo exists {listbox_path}") == "1":
                return listbox_path
            return None
        except tk.TclError:
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

    def open_dropdown_keep_focus(self):
        """Open dropdown while keeping focus on entry."""
        if not self.is_dropdown_open():
            self.combobox.tk.call("ttk::combobox::PostProgrammatic", self.combobox._w)
            # Set light grey background when opening with focus kept on entry
            self._set_unfocused_appearance()
            # Set up bindings after dropdown is open
            self.combobox.after_idle(self._setup_listbox_bindings)

    def open_dropdown_transfer_focus(self):
        """Open dropdown and transfer focus to listbox."""
        if not self.is_dropdown_open():
            self.combobox.event_generate("<Button-1>")
            # Set up bindings after dropdown is open
            self.combobox.after_idle(self._setup_listbox_bindings)

    def transfer_focus_to_listbox(self, direction=None):
        """
        Transfer focus to dropdown listbox and optionally send up/down keystroke.

        Args:
            direction (str, optional): 'up' or 'down' to send corresponding keystroke
        """
        try:
            listbox = f"{self.combobox._w}.popdown.f.l"

            # Set up bindings first
            self._setup_listbox_bindings()

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
                    except ValueError:
                        # Don't select anything if current text isn't found
                        pass

                # Maintain unfocused appearance if listbox doesn't have focus
                if not self.listbox_has_focus:
                    self._set_unfocused_appearance()

                # Set up bindings after updating
                self._setup_listbox_bindings()

            except tk.TclError:
                self.combobox["values"] = filtered_values

    def hide_dropdown(self):
        """Hide the combobox popup."""
        if self.is_dropdown_open():
            self.combobox.event_generate("<Button-1>")
            # Reset focus state when dropdown closes
            self.listbox_has_focus = False
            self._bindings_set = False  # Reset bindings flag


class ComboboxEventHandler:
    """Handles keyboard and selection events for combobox."""

    def __init__(self, combobox, dropdown_manager, autocomplete):
        self.combobox = combobox
        self.dropdown_manager = dropdown_manager
        self.autocomplete = autocomplete

    def bind_events(self):
        """Bind all events to the combobox."""
        self.combobox.bind("<KeyPress-Down>", self.on_down_key)
        self.combobox.bind("<KeyPress-Up>", self.on_up_key)
        self.combobox.bind("<<ComboboxSelected>>", self.on_selection)
        self.combobox.bind("<KeyRelease>", self.handle_keyrelease)
        self.combobox.configure(postcommand=lambda: self.dropdown_manager._set_focused_appearance())

    def on_down_key(self, event):
        """Handle Down key - open dropdown and transfer focus to listbox."""
        if not self.dropdown_manager.is_dropdown_open():
            self.dropdown_manager.open_dropdown_transfer_focus()
            return "break"

        if self.combobox.focus_get() == self.combobox:
            self.dropdown_manager.transfer_focus_to_listbox("down")
            return "break"

    def on_up_key(self, event):
        """Handle Up key - open dropdown and transfer focus to listbox."""
        if self.combobox.focus_get() == self.combobox:
            self.dropdown_manager.transfer_focus_to_listbox("up")
            return "break"

    def handle_keyrelease(self, event):
        """Handle key release events for navigation and selection."""
        # Filter out shift key releases
        if event.keysym in ("Shift_L", "Shift_R"):
            return

        if event.keysym == "Escape":
            self.combobox.master.withdraw()
            return

        if event.keysym == "Return":
            self.combobox.master.withdraw()
            return

        self.autocomplete.handle_keyrelease(event)

        # Process text input and determine if dropdown should be shown
        open_dropdown = False
        if self.combobox.text_input_callback:
            open_dropdown = self.combobox.text_input_callback()

        # Show dropdown if needed and if a printable character or backspace was entered
        if open_dropdown and (
            (event.char and event.char.isprintable()) or event.keysym == "BackSpace"
        ):
            if not self.dropdown_manager.is_dropdown_open():
                self.dropdown_manager.open_dropdown_keep_focus()
        elif not open_dropdown:
            self.dropdown_manager.hide_dropdown()

    def on_selection(self, event):
        """Handle combobox selection event."""
        self.combobox._finalize_selection()


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
        self.selection_callback = None
        self.text_input_callback = None
        self.keypress_callback = None

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

    def _finalize_selection(self):
        """Process the selected item and notify via callback."""
        selected = self.get()
        if selected and self.selection_callback:
            self.selection_callback(selected)
        self.master.withdraw()

    def _reset(self):
        """Reset the combobox content and autocomplete state."""
        self.delete(0, tk.END)
        self._autocomplete.reset()

    # Public API methods
    def set_selection_callback(self, callback: Callable[[str], None]) -> None:
        """Set the callback function for when a selection is made."""
        self.selection_callback = callback

    def set_text_input_callback(self, callback: Callable[[str], None]) -> None:
        """Set the callback function for when text changes."""
        self.text_input_callback = callback

    def update_values(self, values: list[str]) -> None:
        """Update the combobox values and autocomplete list."""
        self.values_list = values
        self["values"] = values
        self._autocomplete.set_completion_list(values)

        # Update dropdown if open
        if self.dropdown_manager.is_dropdown_open():
            self.dropdown_manager.update_listbox_directly(values)
