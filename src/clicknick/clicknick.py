import os
import tkinter as tk
from ctypes import windll
from tkinter import filedialog, ttk

from .dialogs import AboutDialog, OdbcWarningDialog
from .filters import (  # preserve lru_cache
    ContainsFilter,
    ContainsPlusFilter,
    NoneFilter,
    PrefixFilter,
)
from .nickname_manager import NicknameManager
from .overlay import Overlay
from .settings import AppSettings
from .window_detector import ClickWindowDetector
from .window_mapping import CLICK_PLC_WINDOW_MAPPING

# Set DPI awareness for better UI rendering
windll.shcore.SetProcessDpiAwareness(1)


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
        self.click_instances = []  # Will store (id, title, filename) tuples
        self.using_database = False  # Flag to track if database is being used

    def _setup_styles(self):
        """Configure ttk styles for the application."""
        style = ttk.Style()

        # Configure common styles
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=2)

        # Status label styles
        style.configure("Status.TLabel", foreground="blue")
        style.configure("Ready.TLabel", foreground="blue")
        style.configure("Error.TLabel", foreground="red")
        style.configure("Connected.TLabel", foreground="green")

    def _on_instance_selected(self, event=None):
        """Handle instance selection from combobox."""
        selected_text = self.selected_instance_var.get()
        if not selected_text:
            return

        # Find the matching instance
        for _, (pid, title, filename) in enumerate(self.click_instances):
            if filename == selected_text:
                self.connect_to_instance(pid, title, filename)
                break

    def _create_click_instances_section(self, parent):
        """Create the Click.exe instances section."""
        instances_frame = ttk.LabelFrame(
            parent, text="Click PLC Instances", padding="10"
        )  # Reduce from 15 to 10

        # Create frame for combobox and refresh button
        selection_frame = ttk.Frame(instances_frame)

        # Instance selection combobox
        instance_label = ttk.Label(selection_frame, text="Select Instance:")
        self.instances_combobox = ttk.Combobox(
            selection_frame, textvariable=self.selected_instance_var, state="readonly", width=50
        )

        # Refresh button with icon-like text
        refresh_button = ttk.Button(
            selection_frame, text="⟳", width=3, command=self.refresh_click_instances
        )

        # Bind combobox selection to auto-connect
        self.instances_combobox.bind("<<ComboboxSelected>>", self._on_instance_selected)

        # Layout
        instance_label.pack(side=tk.LEFT, padx=(0, 8))  # Reduce from 10 to 8
        self.instances_combobox.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )  # Reduce from 10 to 8
        refresh_button.pack(side=tk.RIGHT)

        selection_frame.pack(fill=tk.X)  # Remove pady

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
        options_frame = ttk.LabelFrame(
            parent, text="Search Options", padding="10"
        )  # Reduce from 15 to 10

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
        filter_label.pack(side=tk.LEFT, padx=(0, 8))  # Reduce from no padding to consistent 8
        none_radio.pack(side=tk.LEFT, padx=(0, 8))  # Reduce from 5 to 8 for consistency
        prefix_radio.pack(side=tk.LEFT, padx=(0, 8))
        contains_radio.pack(side=tk.LEFT, padx=(0, 8))
        contains_plus_radio.pack(side=tk.LEFT)  # Last item doesn't need right padding
        filter_frame.pack(fill=tk.X, pady=(0, 8))  # Reduce from 5 to 8

        # Add sorting option
        sort_check = ttk.Checkbutton(
            options_frame,
            text="Sort by Nickname (alphabetically)",
            variable=self.settings.sort_by_nickname_var,
            command=self._on_sort_option_changed,
        )
        sort_check.pack(anchor=tk.W, pady=(0, 6))  # Add consistent spacing

        # Info tooltip checkbox
        tooltip_check = ttk.Checkbutton(
            options_frame,
            text="Show Nickname tooltips",
            variable=self.settings.show_info_tooltip_var,
        )
        tooltip_check.pack(anchor=tk.W, pady=(0, 6))

        # SC/SD exclusion checkbox
        sc_sd_check = ttk.Checkbutton(
            options_frame, text="Exclude SC/SD Addresses", variable=self.settings.exclude_sc_sd_var
        )
        sc_sd_check.pack(anchor=tk.W, pady=(0, 6))  # Remove padx, standardize pady

        # Exclude nicknames containing entry
        exclude_frame_entry = ttk.Frame(options_frame)
        exclude_label = ttk.Label(exclude_frame_entry, text="Exclude nicknames containing:")
        exclude_entry = ttk.Entry(
            exclude_frame_entry, textvariable=self.settings.exclude_nicknames_var
        )

        # Add placeholder text
        placeholder_text = "name1, name2, name3"

        # Functions to handle placeholder behavior
        def on_entry_focus_in(event):
            if exclude_entry.get() == placeholder_text:
                self.settings.exclude_nicknames_var.set("")
                exclude_entry.config(foreground="black")

        def on_entry_focus_out(event):
            if not exclude_entry.get().strip():
                self.settings.exclude_nicknames_var.set(placeholder_text)
                exclude_entry.config(foreground="gray")

        # Initialize with placeholder if empty
        if not self.settings.exclude_nicknames_var.get():
            self.settings.exclude_nicknames_var.set(placeholder_text)
            exclude_entry.config(foreground="gray")

        # Bind focus events
        exclude_entry.bind("<FocusIn>", on_entry_focus_in)
        exclude_entry.bind("<FocusOut>", on_entry_focus_out)

        exclude_label.pack(side=tk.LEFT, padx=(0, 8))  # Reduce from 5 to 8, remove left padding
        exclude_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)  # Remove padx
        exclude_frame_entry.pack(fill=tk.X)  # Remove padx and pady

        # Pack the main frame
        options_frame.pack(fill=tk.X, pady=(0, 12))  # Reduce from 5 to 12 for consistency

    def _create_status_section(self, parent):
        """Create the status and control section."""
        status_frame = ttk.Frame(parent)

        # Create widgets
        self.status_label = ttk.Label(
            status_frame, textvariable=self.status_var, style="Status.TLabel"
        )
        self.start_button = ttk.Button(status_frame, text="Start", command=self.toggle_monitoring)

        # Layout widgets
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.start_button.pack(side=tk.RIGHT)

        # Pack the frame
        status_frame.pack(fill=tk.X, pady=(8, 0))  # Reduce from 10 to 8, only top padding

    def _create_about_dialog(self):
        """Create and show the About dialog."""
        AboutDialog(self.root, get_version(), self.nickname_manager)

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
        self._create_status_section(main_frame)

        # Pack the main frame
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Initial refresh of Click instances
        self.refresh_click_instances()

    def _show_odbc_warning(self):
        """Show a warning dialog about missing ODBC drivers."""
        OdbcWarningDialog(self.root)

    def _check_odbc_drivers_and_warn(self):
        """Check for ODBC drivers and show warning if none available."""
        if not self.nickname_manager.has_access_driver():
            self._show_odbc_warning()
            return False
        return True

    def __init__(self):
        # Create main window
        self.root = tk.Tk()
        self.root.title("ClickNick App")

        # Hide the window immediately
        self.root.withdraw()

        # Initialize settings first
        self.settings = AppSettings()

        # Initialize monitoring state early (before any UI creation)
        self.monitoring = False
        self.monitor_task_id = None

        # Connected Click.exe instance
        self.connected_click_pid = None
        self.connected_click_title = None
        self.connected_click_filename = None

        self.filter_strategies = {
            "none": NoneFilter(),
            "prefix": PrefixFilter(),
            "contains": ContainsFilter(),
            "containsplus": ContainsPlusFilter(),
        }

        # Initialize core components
        self.nickname_manager = NicknameManager(self.settings, self.filter_strategies)
        self.detector = ClickWindowDetector(CLICK_PLC_WINDOW_MAPPING, self)

        # Initialize overlay early (before UI creation)
        self.overlay = None

        # Set the icon
        try:
            app_dir = os.path.dirname(os.path.abspath(__file__))
            icon_path = os.path.join(app_dir, "clicknick_logo.ico")
            self.root.iconbitmap(icon_path)
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
        self.root.deiconify()

        # Check for ODBC drivers and warn if missing
        self.root.after(1000, self._check_odbc_drivers_and_warn)  # Delay to show after UI loads

        # Combobox overlay (initialized when needed)
        self.overlay = None

    def _update_status(self, message, style="normal"):
        """Update status message with appropriate style."""
        self.status_var.set(message)
        if style == "error":
            self.status_label.configure(style="Error.TLabel")
        elif style == "connected":
            self.status_label.configure(style="Connected.TLabel")
        else:
            self.status_label.configure(style="Status.TLabel")

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
                self._update_status("No Click instances found", "error")
                return

            # Update instance data
            self.click_instances = click_instances
            filenames = [filename for _, _, filename in click_instances]
            self.instances_combobox["values"] = filenames

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
            self._update_status(f"Error: {e!s}", "error")

    def load_csv(self):
        """Load nicknames from CSV file."""
        if not self.csv_path_var.get():
            self._update_status("Error: No CSV file selected", "error")
            return

        # Try to load from CSV
        if self.nickname_manager.load_csv(self.csv_path_var.get()):
            # Apply user's sorting preference
            self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)

            self._update_status("Loaded nicknames from CSV", "ready")
            self.using_database = False

            # Auto-start monitoring if connected and not already started
            if self.connected_click_pid and not self.monitoring:
                self.start_monitoring()
        else:
            self._update_status("Failed to load from CSV", "error")

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
        """Load nicknames directly from the CLICK database."""
        if not self.connected_click_pid:
            self._update_status("Error: Not connected to Click instance", "error")
            return

        # Check if ODBC drivers are available
        if not self.nickname_manager.has_access_driver():
            self._update_status("Error: No Microsoft Access ODBC drivers installed", "error")
            self._show_odbc_warning()
            return

        # Clear the CSV path to indicate we're using the database
        self.csv_path_var.set("")

        # Try to load from database
        success = self.nickname_manager.load_from_database(
            click_pid=self.connected_click_pid,
            click_hwnd=self.detector.get_window_handle(self.connected_click_pid),
        )

        if success:
            # Apply user's sorting preference
            self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)

            self._update_status("Loaded nicknames from database", "ready")
            self.using_database = True

            # Auto-start monitoring if not already started
            if not self.monitoring:
                self.start_monitoring()
        else:
            self._update_status("Failed to load from database", "error")
            self.using_database = False

    def connect_to_instance(self, pid, title, filename):
        """Connect to a specific Click.exe instance."""
        # Stop monitoring if currently active
        if self.monitoring:
            self.stop_monitoring()

        # Reset connection state
        self.connected_click_pid = None
        self.connected_click_title = None
        self.connected_click_filename = None
        self.using_database = False

        # Clear CSV path when switching instances
        self.csv_path_var.set("")

        # Reset nickname manager (reuse filter strategies to preserve cache)
        self.nickname_manager = NicknameManager(self.settings, self.filter_strategies)

        # Store the new connection FIRST
        self.connected_click_pid = pid
        self.connected_click_title = title
        self.connected_click_filename = filename

        # Update status
        self._update_status(f"Connected to {filename}", "connected")

        # Try to load nicknames from database automatically only if ODBC drivers are available
        if self.nickname_manager.has_access_driver():
            # Now load from the NEW instance's database
            success = self.nickname_manager.load_from_database(
                click_pid=self.connected_click_pid,
                click_hwnd=self.detector.get_window_handle(self.connected_click_pid),
            )

            if success:
                # Apply user's sorting preference
                self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)
                self._update_status(f"Loaded nicknames from {filename} database", "ready")
                self.using_database = True
            else:
                self._update_status(f"Connected to {filename} - database load failed", "error")
        else:
            self._update_status("Ready. File → Load Nicknames... to begin.", "connected")

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
            _, allowed_addresses = self.detector.update_window_info(window_class, edit_control)

            # Show the overlay with filtered nicknames
            self.overlay.show_combobox(allowed_addresses)

        except Exception as e:
            print(f"Error showing overlay: {e}")

    def _monitor_task(self):
        """Monitor task that runs every 100ms using after."""
        if not self.monitoring:
            return

        # Check if connected Click.exe still exists
        if not self.detector.check_window_exists(self.connected_click_pid):
            self._update_status("Connected Click instance closed", "error")
            self.stop_monitoring()
            return

        # Skip detection if overlay is visible and being managed
        if self.overlay and self.overlay.is_active():
            self.monitor_task_id = self.root.after(100, self._monitor_task)
            return

        # Check for popups belonging to our parent Click.exe
        child_info = self.detector.detect_child_window(self.connected_click_pid)
        if child_info:
            window_id, window_class, edit_control = child_info
            if not self.detector.field_has_text(edit_control, window_id):
                self._handle_popup_window(window_id, window_class, edit_control)
        else:
            # Hide overlay if no valid popup window is detected
            if self.overlay:
                self.overlay.withdraw()

        # Schedule next check
        self.monitor_task_id = self.root.after(100, self._monitor_task)

    def start_monitoring(self):
        """Start monitoring for window changes."""
        # Check if we have nicknames loaded (either from CSV or database)
        if not self.nickname_manager.is_loaded:
            csv_path = self.csv_path_var.get()
            if csv_path:
                # Load from CSV
                if not self.nickname_manager.load_csv(csv_path):
                    self._update_status("Error: Failed to load CSV", "error")
                    return
                # Apply sorting preference
                self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)
            else:
                # Try loading from database
                if not self.nickname_manager.load_from_database(
                    click_pid=self.connected_click_pid,
                    click_hwnd=self.detector.get_window_handle(self.connected_click_pid),
                ):
                    self._update_status("Error: No nickname source available", "error")
                    return
                # Apply sorting preference
                self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)

        # Validate connection to Click instance
        if not self.connected_click_pid:
            self._update_status("Error: Not connected to Click instance", "error")
            return

        # Start monitoring using after
        self.monitoring = True
        self._monitor_task()

        # Update UI
        self._update_status(f"Monitoring active for {self.connected_click_filename}", "connected")
        self.start_button.configure(text="Stop")

    def stop_monitoring(self):
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

        self._update_status("Monitoring stopped", "status")
        self.start_button.configure(text="Start")

    def toggle_monitoring(self):
        """Start or stop monitoring."""
        if self.monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def open_url(self, url):
        """Open URL in default browser."""
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception as e:
            self._update_status(f"Could not open browser: {e}", "error")

    def on_closing(self):
        """Handle application shutdown."""
        if self.monitoring:
            self.stop_monitoring()
        self.root.destroy()


def main() -> None:
    """Entry point for the application."""
    app = ClickNickApp()
    app.root.mainloop()


if __name__ == "__main__":
    main()  # Call the main function when run directly
