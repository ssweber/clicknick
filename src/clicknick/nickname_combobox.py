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

    def open_dropdown_transfer_focus(self):
        """Open dropdown and transfer focus to listbox."""
        if not self.is_dropdown_open():
            self.combobox.event_generate("<Button-1>")

    def transfer_focus_to_listbox(self):
        """Transfer focus to dropdown listbox."""
        try:
            listbox = f"{self.combobox._w}.popdown.f.l"
            self.combobox.tk.call("focus", listbox)
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

                    # Find the index of the item that matches the current text
                    try:
                        selection_index = filtered_values.index(current_text)
                    except ValueError:
                        selection_index = 0  # Default to first item if not found

                    self.combobox.tk.call(listbox, "selection", "clear", 0, "end")
                    self.combobox.tk.call(listbox, "selection", "set", selection_index)
                    self.combobox.tk.call(listbox, "activate", selection_index)
            except tk.TclError:
                self.combobox["values"] = filtered_values

    def hide_dropdown(self):
        """Hide the combobox popup."""
        self.combobox.master.withdraw()


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
        self.combobox.bind("<KeyPress>", self.on_keypress)
        self.combobox.bind("<<ComboboxSelected>>", self.on_selection)
        self.combobox.bind("<KeyRelease>", self.handle_keyrelease)

    def on_keypress(self, event):
        """Open dropdown on typing while keeping focus on entry."""
        if event.keysym in ("Up", "Down", "Left", "Right", "Escape", "Return", "Tab"):
            return

        if event.char and event.char.isprintable():
            if not self.dropdown_manager.is_dropdown_open():
                self.dropdown_manager.open_dropdown_keep_focus()

    def on_down_key(self, event):
        """Handle Down key - open dropdown and transfer focus to listbox."""
        if not self.dropdown_manager.is_dropdown_open():
            self.dropdown_manager.open_dropdown_transfer_focus()
            return "break"

        if self.combobox.focus_get() == self.combobox:
            self.dropdown_manager.transfer_focus_to_listbox()
            return "break"

    def on_up_key(self, event):
        """Handle Up key - open dropdown and transfer focus to listbox."""
        if self.combobox.focus_get() == self.combobox:
            self.dropdown_manager.transfer_focus_to_listbox()
            return "break"

    def handle_keyrelease(self, event):
        """Handle key release events for navigation and selection."""
        if event.keysym == "Escape":
            self.dropdown_manager.hide_dropdown()
            return

        if event.keysym == "Return":
            self.combobox._finalize_selection()
            return

        self.autocomplete.handle_keyrelease(event)

        # Notify text change instead of filtering internally
        if self.combobox.text_change_callback:
            self.combobox.text_change_callback(self.combobox.get())

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
        self.text_change_callback = None

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

    def set_text_change_callback(self, callback: Callable[[str], None]) -> None:
        """Set the callback function for when text changes."""
        self.text_change_callback = callback

    def update_values(self, values: list[str]) -> None:
        """Update the combobox values and autocomplete list."""
        self.values_list = values
        self["values"] = values
        self._autocomplete.set_completion_list(values)

        # Update dropdown if open
        if self.dropdown_manager.is_dropdown_open():
            self.dropdown_manager.update_listbox_directly(values)
