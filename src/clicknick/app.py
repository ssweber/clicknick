import tkinter as tk
from ctypes import windll
from tkinter import PhotoImage, filedialog, font, ttk

from .config import AppSettings
from .data.nickname_manager import NicknameManager
from .detection.window_detector import ClickWindowDetector
from .detection.window_mapping import CLICK_PLC_WINDOW_MAPPING
from .resources.icon_data import ICON_PNG_BASE64
from .utils.filters import (  # preserve lru_cache
    ContainsFilter,
    ContainsPlusFilter,
    NoneFilter,
    PrefixFilter,
)
from .utils.mdb_shared import find_fallback_csv, set_csv_only_mode
from .views.dialogs import AboutDialog, CsvFallbackDialog, OdbcWarningDialog
from .views.overlay import Overlay

# Set DPI awareness for better UI rendering
windll.shcore.SetProcessDpiAwareness(1)

# Dev mode flag - enables in-progress features
_DEV_MODE = False


def get_version():
    """Get version from package metadata."""
    try:
        from importlib.metadata import version

        return version("clicknick")  # Replace with your actual package name
    except Exception:
        return "Development"


class ClickNickApp:
    """Main application for the ClickNick App."""

    def _setup_variables(self):
        """Initialize Tkinter variables."""
        self.csv_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Not connected")
        self.selected_instance_var = tk.StringVar()  # Add this line
        self.click_instances = []  # Will store ClickInstance objects
        self.using_database = False  # Flag to track if database is being used
        self._odbc_warning_shown = False

    def _setup_styles(self):
        """Configure ttk styles for the application."""
        style = ttk.Style()

        # Configure common styles
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=2)

        # Status label styles
        bold_font = (self._default_family, self._default_size, "bold")  # Only add 'bold'

        # Configure all label styles with icons and consistent font
        style.configure(
            "Status.TLabel",
            foreground="#64B5F6",  # Blue 300 (lighter than Connected)
            font=bold_font,
        )

        style.configure(
            "Connected.TLabel",
            foreground="#1976D2",  # Blue 700 (standard "connected" in Material)
            font=bold_font,
        )

        style.configure(
            "Error.TLabel",
            foreground="#D32F2F",  # Red 700 (Material error color)
            font=bold_font,
        )

    def _on_instance_selected(self, event=None):
        """Handle instance selection from combobox."""
        selected_text = self.selected_instance_var.get()
        if not selected_text:
            return

        # Find the matching instance
        for instance in self.click_instances:
            if instance.filename == selected_text:
                self.connect_to_instance(
                    instance.pid, instance.title, instance.filename, instance.hwnd
                )
                break

    def _create_click_instances_section(self, parent):
        """Create the Click.exe instances section."""
        instances_frame = ttk.LabelFrame(
            parent, text="ClickPLC Windows", padding="10"
        )  # Reduce from 15 to 10

        # Create frame for combobox and refresh button
        selection_frame = ttk.Frame(instances_frame)

        # Instance selection combobox
        instance_label = ttk.Label(selection_frame, text="Select Window:")
        self.instances_combobox = ttk.Combobox(
            selection_frame, textvariable=self.selected_instance_var, state="readonly", width=30
        )

        # Refresh button with icon-like text
        refresh_button = ttk.Button(
            selection_frame, text="⟳", width=3, command=self.refresh_click_instances
        )
        self.start_button = ttk.Button(
            selection_frame, text="▶ Start", command=self.toggle_monitoring
        )

        # Bind combobox selection to auto-connect
        self.instances_combobox.bind("<<ComboboxSelected>>", self._on_instance_selected)

        # Layout
        instance_label.pack(side=tk.LEFT, padx=(0, 8))  # Reduce from 10 to 8
        self.instances_combobox.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )  # Reduce from 10 to 8
        refresh_button.pack(side=tk.RIGHT)
        self.start_button.pack(side=tk.RIGHT)

        selection_frame.pack(fill=tk.X)  # Remove pady

        self.status_label = ttk.Label(
            instances_frame, textvariable=self.status_var, style="Status.TLabel"
        )

        # Layout widgets
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Pack the main frame
        instances_frame.pack(fill=tk.X, pady=(0, 12))  # Reduce from 15 to 12

    def _on_sort_option_changed(self):
        """Handle changes to the sort option."""
        if self.nickname_manager.is_loaded:
            # Apply the new sorting preference
            self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)

            # Regenerate abbreviation tags after sorting
            self.nickname_manager._generate_abbreviation_tags()

    def _create_options_section(self, parent):
        """Create the options section."""
        options_frame = ttk.LabelFrame(parent, text="Autocomplete Options", padding=10)

        # Search mode widgets
        filter_frame = ttk.Frame(options_frame)
        filter_label = ttk.Label(filter_frame, text="Filter Mode:")
        none_radio = ttk.Radiobutton(
            filter_frame,
            text="None",
            variable=self.settings.search_var,
            value="none",
        )
        prefix_radio = ttk.Radiobutton(
            filter_frame,
            text="Prefix Only",
            variable=self.settings.search_var,
            value="prefix",
        )
        contains_radio = ttk.Radiobutton(
            filter_frame,
            text="Contains",
            variable=self.settings.search_var,
            value="contains",
        )
        contains_plus_radio = ttk.Radiobutton(
            filter_frame,
            text="Abbreviations",
            variable=self.settings.search_var,
            value="containsplus",
        )

        # Layout filter widgets
        filter_label.pack(side=tk.LEFT, padx=(0, 8))
        none_radio.pack(side=tk.LEFT, padx=(0, 8))
        prefix_radio.pack(side=tk.LEFT, padx=(0, 8))
        contains_radio.pack(side=tk.LEFT, padx=(0, 8))
        contains_plus_radio.pack(side=tk.LEFT)
        filter_frame.pack(fill=tk.X, pady=(0, 8))

        # Checkbox row (Sort, Tooltips, SC/SD)
        checkbox_frame = ttk.Frame(options_frame)  # New frame to hold checkboxes in one row
        checkbox_frame.pack(fill=tk.X, pady=(0, 6))

        # Sort A-Z checkbox
        sort_check = ttk.Checkbutton(
            checkbox_frame,
            text="Sort A→Z",
            variable=self.settings.sort_by_nickname_var,
            command=self._on_sort_option_changed,
        )
        sort_check.pack(side=tk.LEFT, padx=(0, 8))

        # Tooltip checkbox
        tooltip_check = ttk.Checkbutton(
            checkbox_frame,
            text="Show Tooltips",
            variable=self.settings.show_info_tooltip_var,
        )
        tooltip_check.pack(side=tk.LEFT, padx=(0, 8))

        # SC/SD exclusion checkbox
        sc_sd_check = ttk.Checkbutton(
            checkbox_frame, text="Exclude SC/SD Addresses", variable=self.settings.exclude_sc_sd_var
        )
        sc_sd_check.pack(side=tk.LEFT)

        # Exclude nicknames containing entry
        exclude_frame_entry = ttk.Frame(options_frame)
        exclude_label = ttk.Label(exclude_frame_entry, text="Exclude nicknames containing:")
        exclude_entry = ttk.Entry(
            exclude_frame_entry, textvariable=self.settings.exclude_nicknames_var
        )

        # Placeholder text logic
        placeholder_text = AppSettings.EXCLUDE_PLACEHOLDER_TEXT

        def on_entry_focus_in(event):
            if exclude_entry.get() == placeholder_text:
                self.settings.exclude_nicknames_var.set("")
                exclude_entry.config(foreground="black")

        def on_entry_focus_out(event):
            if not exclude_entry.get().strip():
                self.settings.exclude_nicknames_var.set(placeholder_text)
                exclude_entry.config(foreground="gray")

        if not self.settings.exclude_nicknames_var.get():
            self.settings.exclude_nicknames_var.set(placeholder_text)
            exclude_entry.config(foreground="gray")

        exclude_entry.bind("<FocusIn>", on_entry_focus_in)
        exclude_entry.bind("<FocusOut>", on_entry_focus_out)

        exclude_label.pack(side=tk.LEFT, padx=(0, 8))
        exclude_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        exclude_frame_entry.pack(fill=tk.X, pady=(0, 6))

        # Pack the main frame
        options_frame.pack(fill=tk.X, pady=(0, 12))

    def _create_about_dialog(self):
        """Create and show the About dialog."""
        AboutDialog(self.root, get_version(), self.nickname_manager)

    def _show_odbc_warning(self):
        """Show a warning dialog about missing ODBC drivers."""
        OdbcWarningDialog(self.root)

    def _update_status(self, message, style="normal"):
        """Update status message with appropriate style."""
        self.status_var.set(message)
        if style == "error":
            self.status_label.configure(style="Error.TLabel")
        elif style == "connected":
            self.status_label.configure(style="Connected.TLabel")
        else:
            self.status_label.configure(style="Status.TLabel")

    def _open_address_editor(self):
        """Open the Address Editor window.

        Multiple windows can be opened and they will share the same data.
        Changes made in one window are automatically reflected in others.
        """
        if not self.connected_click_pid:
            self._update_status("Connect to a ClickPLC window first", "error")
            return

        # Check for ODBC drivers (MDB mode requires them)
        csv_path = self.csv_path_var.get()
        if not csv_path and not self.nickname_manager.has_access_driver():
            self._show_odbc_warning()
            return

        # Use the app-level SharedAddressData
        if self._shared_address_data is None:
            self._update_status("No data loaded", "error")
            return

        try:
            from .views.address_editor.window import AddressEditorWindow

            AddressEditorWindow(
                self.root,
                shared_data=self._shared_address_data,
                click_filename=self.connected_click_filename or "",
            )

        except Exception as e:
            import traceback

            traceback.print_exc()
            self._update_status(f"Error opening editor: {e}", "error")

    def _open_dataview_editor(self):
        """Open the Dataview Editor window, or focus if already open.

        The dataview editor allows creating and editing CLICK DataView files (.cdv).
        Only one DataviewEditorWindow can be open at a time.
        """
        if not self.connected_click_pid:
            self._update_status("Connect to a ClickPLC window first", "error")
            return

        # Use the app-level SharedAddressData
        if self._shared_address_data is None:
            self._update_status("No data loaded", "error")
            return

        try:
            from .data.shared_dataview import SharedDataviewData
            from .utils.mdb_shared import get_project_path_from_hwnd
            from .views.dataview_editor.window import DataviewEditorWindow

            # Get project path from connected Click window
            project_path = get_project_path_from_hwnd(self.connected_click_hwnd)

            # Create or reuse shared dataview data
            if not hasattr(self, "_dataview_editor_shared_data"):
                self._dataview_editor_shared_data = None
            if not hasattr(self, "_dataview_editor_project_path"):
                self._dataview_editor_project_path = None

            # Create new shared data if none exists or if project changed
            if (
                self._dataview_editor_shared_data is None
                or self._dataview_editor_project_path != project_path
            ):
                self._dataview_editor_shared_data = SharedDataviewData(
                    project_path=project_path,
                    address_shared_data=self._shared_address_data,
                )
                self._dataview_editor_project_path = project_path

            # If window already open, focus it instead of creating a new one
            if self._dataview_editor_shared_data._window is not None:
                try:
                    self._dataview_editor_shared_data._window.lift()
                    self._dataview_editor_shared_data._window.focus_force()
                    return
                except Exception:
                    # Window was destroyed, clear reference
                    self._dataview_editor_shared_data._window = None

            DataviewEditorWindow(
                self.root,
                shared_data=self._dataview_editor_shared_data,
                title_suffix=self.connected_click_filename or "",
            )

        except Exception as e:
            import traceback

            traceback.print_exc()
            self._update_status(f"Error opening dataview editor: {e}", "error")

    def _create_menu_bar(self):
        """Create the application menu bar."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Exit", command=self.on_closing)
        file_menu.add_separator()
        file_menu.add_command(label="Load Nicknames from CSV...", command=self.browse_and_load_csv)

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Address Editor...", command=self._open_address_editor)
        tools_menu.add_command(label="Dataview Editor...", command=self._open_dataview_editor)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About ClickNick...", command=self._create_about_dialog)
        help_menu.add_separator()
        help_menu.add_command(
            label="GitHub Repository",
            command=lambda: self.open_url("https://github.com/ssweber/clicknick"),
        )
        help_menu.add_command(
            label="Report Issue",
            command=lambda: self.open_url("https://github.com/ssweber/clicknick/issues"),
        )

    def _create_widgets(self):
        """Create all UI widgets."""
        # Add menu bar first
        self._create_menu_bar()

        # Main frame to contain everything with consistent padding
        main_frame = ttk.Frame(self.root, padding="15")  # Reduce from 20 to 15

        # Create all widgets
        self._create_click_instances_section(main_frame)
        self._create_options_section(main_frame)

        # Pack the main frame
        main_frame.pack(fill=tk.BOTH, expand=True)

    def __init__(self):
        # Create main window
        self.root = tk.Tk()
        self.root.title("ClickNick App")

        # Define your base font (family, size, weight)
        self._default_font = font.nametofont("TkDefaultFont")
        self._default_family = self._default_font.cget("family")
        self._default_size = self._default_font.cget("size")

        # Create a style object
        style = ttk.Style(self.root)

        # Set the default font for all ttk widgets
        style.configure(".", font=self._default_font)  # Applies to all widgets

        # Hide the window immediately
        self.root.withdraw()

        # Initialize settings first
        self.settings = AppSettings()

        # Initialize monitoring state early (before any UI creation)
        self.monitoring = False
        self.monitor_task_id = None

        # Connected Click.exe instance
        self.connected_click_pid = None
        self.connected_click_filename = None
        self.connected_click_hwnd = None

        self.filter_strategies = {
            "none": NoneFilter(),
            "prefix": PrefixFilter(),
            "contains": ContainsFilter(),
            "containsplus": ContainsPlusFilter(),
        }

        # Initialize core components
        self.nickname_manager = NicknameManager(self.settings, self.filter_strategies)
        self.detector = ClickWindowDetector(CLICK_PLC_WINDOW_MAPPING, self)

        # Shared address data (single source of truth for all address data)
        self._shared_address_data = None
        self._shared_data_source_path = None

        # Initialize overlay early (before UI creation)
        self.overlay = None

        # Set the icon
        try:
            icon = PhotoImage(data=ICON_PNG_BASE64)
            self.root.iconphoto(True, icon)
            # Keep a reference to prevent garbage collection
            self.root._icon = icon
        except tk.TclError:
            pass  # Continue without icon if it fails

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Setup variables
        self._setup_variables()

        # Setup UI styles
        self._setup_styles()

        # Create UI components
        self._create_widgets()

        # Show the window after everything is created
        self.root.update_idletasks()
        self.root.deiconify()

        # Combobox overlay (initialized when needed)
        self.overlay = None

    def _update_window_title(self):
        """Update window title to reflect current connection and data source."""
        if not self.connected_click_filename:
            self.root.title("ClickNick")
            return

        # Determine source type
        if self.csv_path_var.get():
            source = "CSV"
        elif self.using_database:
            source = "DB"
        else:
            source = ""

        if source:
            self.root.title(f"ClickNick - {self.connected_click_filename} - {source}")
        else:
            self.root.title(f"ClickNick - {self.connected_click_filename}")

    def _check_odbc_drivers_and_warn(self):
        """Check for ODBC drivers and show warning if none available."""
        if not self.nickname_manager.has_access_driver():
            self._show_odbc_warning()
            return False
        return True

    def refresh_click_instances(self):
        """Refresh the list of running Click.exe instances."""
        # Remember currently selected instance
        previously_selected = self.selected_instance_var.get()

        # Clear current data
        self.click_instances = []
        self.instances_combobox["values"] = ()
        self.selected_instance_var.set("")

        try:
            # Get all Click.exe instances from detector
            click_instances = self.detector.get_click_instances()

            if not click_instances:
                self._update_status("⚠ No ClickPLC windows", "error")
                self.start_button.state(["disabled"])  # Disable when no instances
                return

            # Update instance data
            self.click_instances = click_instances
            filenames = [instance.filename for instance in click_instances]
            self.instances_combobox["values"] = filenames
            self.start_button.state(["!disabled"])  # Enable when instances found

            # Try to restore previous selection
            if previously_selected in filenames:
                self.selected_instance_var.set(previously_selected)
            elif filenames:
                # If previous selection not found, select first item
                self.selected_instance_var.set(filenames[0])
                # Auto-connect to first instance
                self._on_instance_selected()

        except Exception as e:
            print(f"Error refreshing Click instances: {e}")
            self._update_status(f"⚠ Error: {e!s}", "error")
            self.start_button.state(["disabled"])  # Disable on error

    def load_csv(self):
        """Load nicknames from CSV file."""
        csv_path = self.csv_path_var.get()
        if not csv_path:
            self._update_status("⚠ No CSV file selected", "error")
            return False

        try:
            from .data.data_source import CsvDataSource
            from .data.shared_data import SharedAddressData

            data_source = CsvDataSource(csv_path)
            self._shared_address_data = SharedAddressData(data_source)
            self._shared_address_data.load_initial_data()
            self._shared_data_source_path = csv_path

            # Start file monitoring for external changes
            self._shared_address_data.start_file_monitoring(self.root)

            # Wire NicknameManager to use SharedAddressData
            self.nickname_manager.set_shared_data(self._shared_address_data)

            # Apply user's sorting preference
            self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)

            self._update_status("✓ CSV loaded", "connected")
            self.using_database = False
            self._update_window_title()
            self.start_monitoring()
            return True
        except Exception as e:
            print(f"Error loading CSV: {e}")
            self._update_status("⚠ CSV load failed", "error")
            return False

    def browse_and_load_csv(self):
        """Browse for and load CSV file from menu."""
        filepath = filedialog.askopenfilename(
            title="Select Nickname CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if filepath:
            self.csv_path_var.set(filepath)
            self.load_csv()

    def load_from_database(self):
        """Start monitoring after SharedAddressData is loaded."""
        if not self.connected_click_pid:
            self._update_status("⚠ Not connected", "error")
            return False

        # Check if ODBC drivers are available
        if not self.nickname_manager.has_access_driver():
            self._update_status("⏹ Stopped - Use File → Load Nicknames... to Start", "status")
            if not self._odbc_warning_shown:
                self._show_odbc_warning()
                self._odbc_warning_shown = True
            return False

        # SharedAddressData already created and loaded in connect_to_instance()
        if self._shared_address_data is None:
            self._update_status("⚠ DB load failed", "error")
            self.using_database = False
            return False

        # Apply user's sorting preference
        self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)

        self._update_status("✓ DB loaded", "connected")
        self.using_database = True
        self._update_window_title()

        self.start_monitoring()
        return True

    def _close_editor_windows(self, prompt_save: bool = True) -> bool:
        """Close all editor windows (Address Editor and Dataview Editor).

        Args:
            prompt_save: If True, prompt to save unsaved changes.

        Returns:
            True if all windows were closed, False if user cancelled.
        """
        # Close Address Editor windows
        if self._shared_address_data is not None:
            if not self._shared_address_data.close_all_windows(prompt_save=prompt_save):
                return False
            self._shared_address_data = None
            self._shared_data_source_path = None

        # Close Dataview Editor window
        if (
            hasattr(self, "_dataview_editor_shared_data")
            and self._dataview_editor_shared_data is not None
        ):
            if self._dataview_editor_shared_data._window is not None:
                try:
                    # Check for unsaved changes in Dataview Editor
                    window = self._dataview_editor_shared_data._window
                    if (
                        prompt_save
                        and hasattr(window, "_has_unsaved_changes")
                        and window._has_unsaved_changes()
                    ):
                        from tkinter import messagebox

                        result = messagebox.askyesnocancel(
                            "Unsaved Changes",
                            "Dataview Editor has unsaved changes. Save before closing?",
                            parent=window,
                        )
                        if result is None:  # Cancel
                            return False
                        if result:  # Yes - save
                            window._save_current_file()
                    window.destroy()
                except Exception:
                    pass  # Window may already be destroyed
            self._dataview_editor_shared_data = None
            self._dataview_editor_project_path = None

        # Disconnect NicknameManager from old data
        self.nickname_manager.set_shared_data(None)
        return True

    def connect_to_instance(self, pid, title, filename, hwnd):
        """Connect to a specific Click.exe instance."""
        # Close any open editor windows first (prompt to save if needed)
        if not self._close_editor_windows(prompt_save=True):
            # User cancelled - don't switch instances
            # Restore combobox selection to current instance
            if self.connected_click_filename:
                self.selected_instance_var.set(self.connected_click_filename)
            return

        # Stop monitoring if currently active
        if self.monitoring:
            self.stop_monitoring()

        # Reset connection state
        self.connected_click_pid = None
        self.connected_click_filename = None
        self.connected_click_hwnd = None
        self.using_database = False

        # Clear CSV path when switching instances
        self.csv_path_var.set("")

        # Store the new connection FIRST (including hwnd to avoid lookup issues)
        self.connected_click_pid = pid
        self.connected_click_filename = filename
        self.connected_click_hwnd = hwnd

        # Check for ODBC drivers - if missing, try CSV fallback
        if not self.nickname_manager.has_access_driver():
            fallback_csv = find_fallback_csv(hwnd)
            if fallback_csv:
                # Show dialog prompting user to save a copy
                default_name = f"{filename.replace('.ckp', '')}_Address.csv"
                dialog = CsvFallbackDialog(self.root, fallback_csv, default_name)
                saved_path = dialog.show()
                if saved_path:
                    # Load from the saved CSV copy
                    self.csv_path_var.set(saved_path)
                    self.load_csv()
                    return
            # No fallback available or user cancelled - show standard ODBC warning
            self._update_status("⏹ Stopped - Use File → Load Nicknames...", "error")
            if not self._odbc_warning_shown:
                self._show_odbc_warning()
                self._odbc_warning_shown = True
            return

        # Create SharedAddressData for the new connection (ODBC available)
        from .data.data_source import MdbDataSource
        from .data.shared_data import SharedAddressData

        data_source = MdbDataSource(
            click_pid=self.connected_click_pid,
            click_hwnd=self.connected_click_hwnd,
        )
        self._shared_address_data = SharedAddressData(data_source)
        self._shared_address_data.load_initial_data()
        self._shared_data_source_path = f"mdb:{pid}:{hwnd}"

        # Start file monitoring for external changes
        self._shared_address_data.start_file_monitoring(self.root)

        # Wire NicknameManager to use SharedAddressData
        self.nickname_manager.set_shared_data(self._shared_address_data)

        # Use centralized database loading method (now just starts monitoring)
        self.load_from_database()

    def _handle_popup_window(self, window_id, window_class, edit_control):
        """Handle the detected popup window by showing or updating the nickname popup."""
        try:
            # Create overlay if it doesn't exist
            if not self.overlay:
                self.overlay = Overlay(
                    self.root,
                    self.nickname_manager,
                )
                self.overlay.set_target_window(window_id, window_class, edit_control)
            else:
                # Update target window info
                self.overlay.set_target_window(window_id, window_class, edit_control)

            # Get allowed types for this window/control
            field_info = self.detector.update_window_info(window_class, edit_control)

            # Show the overlay with filtered nicknames
            self.overlay.show_combobox(field_info.allowed_address_types)

        except Exception as e:
            print(f"Error showing overlay: {e}")

    def _parse_filename_from_title(self, title):
        """Extract filename from window title using centralized parser."""
        return ClickWindowDetector.parse_click_filename(title)

    def _handle_window_closed(self):
        """Handle when connected window is no longer available."""
        self._update_status("⚠ Connected ClickPLC window closed", "error")
        self.stop_monitoring(update_status=False)

        # Force close any open editor windows (can't save - DB is gone)
        if self._shared_address_data is not None:
            self._shared_address_data.force_close_all_windows()
            self._shared_address_data = None
            self._shared_data_source_path = None

        # Disconnect NicknameManager from data
        self.nickname_manager.set_shared_data(None)

        self.root.after(2000, self.refresh_click_instances)

    def _monitor_task(self):
        """Monitor task that runs every 100ms using after."""
        if not self.monitoring:
            return

        # Use the stored HWND from connection time
        window_id = self.connected_click_hwnd

        # First verify window still exists
        if not window_id or not self.detector.check_window_exists(self.connected_click_pid):
            self._handle_window_closed()
            return

        # Direct title check - no list scanning
        current_title = self.detector.get_window_title(window_id)
        new_filename = self._parse_filename_from_title(current_title)

        csv_unloaded = False
        if new_filename and new_filename != self.connected_click_filename:
            # File changed within the same Click window - close editor windows without prompting
            # (user changed file in Click, so data loss is expected)
            has_address_windows = (
                self._shared_address_data is not None
                and len(self._shared_address_data._windows) > 0
            )
            has_dataview_window = (
                hasattr(self, "_dataview_editor_shared_data")
                and self._dataview_editor_shared_data is not None
                and self._dataview_editor_shared_data._window is not None
            )
            if has_address_windows or has_dataview_window:
                from tkinter import messagebox

                messagebox.showinfo(
                    "Project Changed",
                    "The Click project was changed. Editor windows will now close.",
                )
            self._close_editor_windows(prompt_save=False)

            # Clear CSV path if it was set
            if self.csv_path_var.get():
                self.csv_path_var.set("")
                self._update_status("⚠ CSV unloaded - filename changed", "error")
                csv_unloaded = True

            # Update instances list with new filename
            for instance in self.click_instances:
                if instance.pid == self.connected_click_pid:
                    instance.title = current_title
                    instance.filename = new_filename
                    break

            # Update combobox values and selection
            self.instances_combobox["values"] = [inst.filename for inst in self.click_instances]
            self.connected_click_filename = new_filename
            self.selected_instance_var.set(new_filename)

            if csv_unloaded:
                self.using_database = False
                self._update_window_title()
                self.stop_monitoring(update_status=False)
            else:
                # Recreate SharedAddressData for the new MDB file
                if self.nickname_manager.has_access_driver():
                    from .data.data_source import MdbDataSource
                    from .data.shared_data import SharedAddressData

                    data_source = MdbDataSource(
                        click_pid=self.connected_click_pid,
                        click_hwnd=self.connected_click_hwnd,
                    )
                    self._shared_address_data = SharedAddressData(data_source)
                    self._shared_address_data.load_initial_data()
                    self._shared_data_source_path = (
                        f"mdb:{self.connected_click_pid}:{self.connected_click_hwnd}"
                    )

                    # Start file monitoring for external changes
                    self._shared_address_data.start_file_monitoring(self.root)

                    # Wire NicknameManager to use new SharedAddressData
                    self.nickname_manager.set_shared_data(self._shared_address_data)

                    self.using_database = True
                    self._update_window_title()

                self._update_status(f"⚡ Monitoring {new_filename}", "connected")

        # Skip detection if overlay is visible and being managed
        if self.overlay and self.overlay.is_active():
            self.monitor_task_id = self.root.after(100, self._monitor_task)
            return

        # Check for popups belonging to our parent Click.exe
        child_info = self.detector.detect_child_window(self.connected_click_pid)
        if child_info:
            if not self.detector.field_has_text(child_info.edit_control, child_info.window_id):
                self._handle_popup_window(
                    child_info.window_id, child_info.window_class, child_info.edit_control
                )
        else:
            # Hide overlay if no valid popup window is detected
            if self.overlay:
                self.overlay.withdraw()

        # Schedule next check
        self.monitor_task_id = self.root.after(100, self._monitor_task)

    def _start_monitoring_internal(self) -> bool:
        """Internal method to start monitoring without status updates.
        Returns True if successful, False otherwise."""
        # Validate connection to Click instance
        if not self.connected_click_pid:
            self._update_status("⚠ Not connected to ClickPLC window", "error")
            return False

        # Start monitoring using after
        try:
            self.monitoring = True
            self._monitor_task()
            return True
        except Exception as e:
            self._update_status(f"⚠ Monitoring failed: {str(e)}", "error")
            return False

    def _update_status_monitoring(self):
        """Update Status and Button to reflect Monitoring"""
        self._update_status(f"⚡ Monitoring {self.connected_click_filename}", "connected")
        self.start_button.configure(text="⏹ Stop")

    def start_monitoring(self):
        """Start monitoring with delayed status update."""
        if self._start_monitoring_internal():
            # Only schedule status update if successful
            self.root.after(1000, lambda: self._update_status_monitoring())

    def button_start_monitoring(self):
        """Start monitoring with immediate status update."""
        if self._start_monitoring_internal():
            # Only update UI if successful
            self._update_status_monitoring()

    def stop_monitoring(self, update_status=True):
        """Stop monitoring."""
        self.monitoring = False

        # Cancel scheduled task if it exists
        if self.monitor_task_id:
            self.root.after_cancel(self.monitor_task_id)
            self.monitor_task_id = None

        # Destroy overlay if it exists
        if self.overlay:
            self.overlay.withdraw()
            self.overlay = None

        if update_status:
            self._update_status("⏹ Stopped", "status")
        self.start_button.configure(text="▶ Start")

    def toggle_monitoring(self):
        """Start or stop monitoring."""
        if self.monitoring:
            self.stop_monitoring()
        else:
            # Only update button if start was successful
            if self.button_start_monitoring():
                self.start_button.configure(text="⏹ Stop")

    def open_url(self, url):
        """Open URL in default browser."""
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception as e:
            self._update_status(f"⚠ Could not open browser: {e}", "error")

    def on_closing(self):
        """Handle application shutdown."""
        if self.monitoring:
            self.stop_monitoring()
        self.root.destroy()

    def run(self):
        """Run the ClickNick Application"""
        self.refresh_click_instances()
        self.root.mainloop()


def main() -> None:
    """Entry point for the application."""
    app = ClickNickApp()
    app.run()


def main_dev() -> None:
    """Entry point for development mode with in-progress features enabled.

    Args (via sys.argv):
        -csvonly: Force CSV-only mode (pretend ODBC drivers are unavailable)
    """
    import sys

    global _DEV_MODE
    _DEV_MODE = True

    if "-csvonly" in sys.argv:
        set_csv_only_mode(True)
        print("CSV-only mode enabled (ODBC drivers will appear unavailable)")

    app = ClickNickApp()
    app.run()


if __name__ == "__main__":
    main()  # Call the main function when run directly
