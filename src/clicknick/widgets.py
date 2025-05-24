import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from .combobox_autocomplete import PrefixAutocomplete
from .combobox_filter import ContainsFilter, FuzzyFilter, NoneFilter, PrefixFilter
from .shared_ahk import AHK


class ComboboxOverlay(tk.Toplevel):
    """Overlay for nickname selection."""

    def __init__(
        self,
        root,
        nickname_mananger,
        search_var=None,
        fuzzy_threshold_var=None,
        exclude_sc_sd_var=None,
        exclude_nicknames_var=None,
    ):
        super().__init__(root)
        self.title("ClickNickOverlay")
        self.overrideredirect(True)  # No window decorations
        self.attributes("-topmost", True)  # Stay on top
        self.withdraw()  # Hide initially

        # Store exclusion variables
        self.exclude_sc_sd_var = exclude_sc_sd_var
        self.exclude_nicknames_var = exclude_nicknames_var

        # Create the combobox
        # Configure style for wider dropdown
        style = ttk.Style()
        style.configure("Wider.TCombobox", postoffset=(0, 0, 150, 0))  # last value extends width
        self.combobox = NicknameCombobox(self, width=30, style="Wider.TCombobox")
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
        self.bind("<KeyPress-Tab>", self._on_tab)
        self.bind("<Control-Shift-KeyPress-Tab>", self._on_tab)  # Shift+Tab

        # Initialize after IDs
        self.focus_out_after_id = None
        self.debounce_after_id = None

    def _input_current_text(self):
        """Input whatever is currently in the combobox."""
        current_text = self.combobox.get().strip()
        if self.combobox.selection_callback:
            self.combobox.selection_callback(current_text)

    def _on_tab(self, event):
        """Handle tab key to input current text before withdrawing."""
        self._input_current_text()
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
            self._input_current_text()

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
        exclude_sc_sd = False
        exclude_terms = ""

        if self.exclude_sc_sd_var:
            exclude_sc_sd = self.exclude_sc_sd_var.get()

        if self.exclude_nicknames_var:
            exclude_terms = self.exclude_nicknames_var.get()

        nicknames = self.nickname_manager.get_nicknames_for_combobox(
            allowed_types, exclude_sc_sd=exclude_sc_sd, exclude_terms=exclude_terms
        )
        self.combobox.update_values(nicknames)

        # Only show if positioning is successful
        if not self.position_near_edit_control():
            return

    def _on_nickname_selected(self, nickname):
        """
        Handle nickname selection.

        If the nickname corresponds to an address, insert that address.
        Otherwise, pass on the text.
        """
        # First check if it's a known nickname
        address = self.nickname_manager.get_address_for_nickname(nickname)

        if address:
            self._insert_text_to_field(address)
            return
        else:
            self._insert_text_to_field(nickname)
            return

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
        except Exception as e:
            print(f"Error inserting text: {e}")

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


class ComboboxTCLManager:
    """Manages TCL setup for enhanced combobox focus behavior."""

    _tcl_setup_done = False

    @classmethod
    def setup_tcl_if_needed(cls, parent):
        """Setup TCL code once for dual focus behavior."""
        if not cls._tcl_setup_done:
            cls._setup_tcl(parent)
            cls._tcl_setup_done = True

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

        if event.keysym in ("Up", "Down"):
            return

        self.autocomplete.handle_keyrelease(event)
        self.combobox._filter_results()

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

        # Initialize components
        self._init_components()

        # Configure combobox
        self["values"] = self.values_list

        # Setup autocomplete
        self._autocomplete = PrefixAutocomplete(self)
        self._autocomplete.set_completion_list(self.values_list)

        # Setup event handling
        self.event_handler = ComboboxEventHandler(self, self.dropdown_manager, self._autocomplete)
        self.event_handler.bind_events()

    def _init_components(self):
        """Initialize all component managers."""
        self.selection_callback = None

        # Setup search strategy with default value
        self.search_var = tk.StringVar(value="none")
        self.fuzzy_threshold_var = tk.IntVar(value=60)

        # Initialize managers
        self.dropdown_manager = DropdownManager(self)
        self._init_filters()

        # Event handler will be initialized after autocomplete is set up

    def _init_filters(self):
        """Initialize the search strategies"""
        self.strategies = {
            "none": NoneFilter(),
            "prefix": PrefixFilter(),
            "contains": ContainsFilter(),
            "fuzzy": FuzzyFilter(),
        }

    def _filter_results(self):
        """Filter dropdown results based on current text and search strategy"""
        current_text = self.get()

        if self.selection_present():
            sel_start = self.index("sel.first")
            current_text = current_text[:sel_start]

        strategy_name = self.search_var.get()
        strategy = self.strategies.get(strategy_name, self.strategies["none"])

        if strategy_name == "fuzzy" and isinstance(strategy, FuzzyFilter):
            strategy.threshold = self.fuzzy_threshold_var.get()

        filtered_values = strategy.filter_matches(self.values_list, current_text)

        if self.dropdown_manager.is_dropdown_open():
            self.dropdown_manager.update_listbox_directly(filtered_values)
        self["values"] = filtered_values

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

    def set_search_var(self, search_var):
        """Set the variable that controls the search strategy"""
        self.search_var = search_var

    def set_fuzzy_threshold_var(self, fuzzy_threshold_var):
        """Set the variable that controls the fuzzy threshold"""
        self.fuzzy_threshold_var = fuzzy_threshold_var

    def update_values(self, values: list[str]) -> None:
        """Update the combobox values and autocomplete list."""
        self.values_list = values
        self["values"] = values
        self._autocomplete.set_completion_list(values)
