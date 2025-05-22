import tkinter as tk
from ctypes import windll
from tkinter import filedialog, ttk

from .nickname_manager import NicknameManager
from .widgets import NicknamePopup
from .window_detector import ClickWindowDetector
from .window_mapping import CLICK_PLC_WINDOW_MAPPING

# Set DPI awareness for better UI rendering
windll.shcore.SetProcessDpiAwareness(1)


class ClickNickApp:
    """Main application for the ClickNick App."""

    def __init__(self):
        # Initialize core components
        self.nickname_manager = NicknameManager()
        self.detector = ClickWindowDetector(CLICK_PLC_WINDOW_MAPPING, self)

        # Create main window
        self.root = tk.Tk()
        self.root.title("ClickNick App")
        self.root.geometry("500x500")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Setup variables
        self.setup_variables()

        # Setup UI styles
        self.setup_styles()

        # Create UI components
        self.create_widgets()

        # Combobox popup (initialized when needed)
        self.popup = None

        # Monitoring state
        self.monitoring = False
        self.monitor_task_id = None

        # Connected Click.exe instance
        self.connected_click_pid = None
        self.connected_click_title = None
        self.connected_click_filename = None

    def setup_variables(self):
        """Initialize Tkinter variables."""
        self.csv_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Not connected")
        self.search_var = tk.StringVar(value="contains")
        self.fuzzy_threshold_var = tk.IntVar(value=60)  # Default threshold value
        self.threshold_display_var = tk.StringVar(value="60")  # Display value
        self.click_instances = []  # Will store (id, title, filename) tuples
        self.using_database = False  # Flag to track if database is being used

        self.exclude_sc_sd_var = tk.BooleanVar(value=False)
        self.exclude_nicknames_var = tk.StringVar(value="")

    def setup_styles(self):
        """Configure ttk styles for the application."""
        style = ttk.Style()

        # Configure common styles
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=2)

        # Status label styles
        style.configure("Status.TLabel", foreground="blue")
        style.configure("Error.TLabel", foreground="red")
        style.configure("Connected.TLabel", foreground="green")

    def create_widgets(self):
        """Create all UI widgets."""
        # Main frame to contain everything
        main_frame = ttk.Frame(self.root, padding="10 10 10 10")

        # Create all widgets
        self.create_click_instances_section(main_frame)
        self.create_options_section(main_frame)
        self.create_exclude_section(main_frame)  # Add this line
        self.create_status_section(main_frame)
        self.create_csv_section(main_frame)

        # Pack the main frame
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Initial refresh of Click instances
        self.refresh_click_instances()

    def create_exclude_section(self, parent):
        """Create the exclude options section."""
        exclude_frame = ttk.LabelFrame(parent, text="Exclude")

        # SC/SD exclusion checkbox
        sc_sd_check = ttk.Checkbutton(
            exclude_frame, text="Exclude SC/SD Addresses", variable=self.exclude_sc_sd_var
        )
        sc_sd_check.pack(anchor=tk.W, padx=5, pady=2)

        # Exclude nicknames containing entry
        exclude_frame_entry = ttk.Frame(exclude_frame)
        exclude_label = ttk.Label(exclude_frame_entry, text="Exclude nicknames containing:")
        exclude_entry = ttk.Entry(exclude_frame_entry, textvariable=self.exclude_nicknames_var)

        # Add placeholder text
        placeholder_text = "name1, name2, name3"

        # Functions to handle placeholder behavior
        def on_entry_focus_in(event):
            if exclude_entry.get() == placeholder_text:
                self.exclude_nicknames_var.set("")
                exclude_entry.config(foreground="black")

        def on_entry_focus_out(event):
            if not exclude_entry.get().strip():
                self.exclude_nicknames_var.set(placeholder_text)
                exclude_entry.config(foreground="gray")

        # Initialize with placeholder if empty
        if not self.exclude_nicknames_var.get():
            self.exclude_nicknames_var.set(placeholder_text)
            exclude_entry.config(foreground="gray")

        # Bind focus events
        exclude_entry.bind("<FocusIn>", on_entry_focus_in)
        exclude_entry.bind("<FocusOut>", on_entry_focus_out)

        exclude_label.pack(side=tk.LEFT, padx=5)
        exclude_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        exclude_frame_entry.pack(fill=tk.X, padx=5, pady=5)

        # Pack the main frame
        exclude_frame.pack(fill=tk.X, pady=5)

    def create_csv_section(self, parent):
        """Create the CSV file selection section."""
        csv_frame = ttk.LabelFrame(parent, text="Alternative Nickname Source")
        self.csv_frame = csv_frame  # Save reference to frame

        # Create widgets
        csv_label = ttk.Label(csv_frame, text="CSV File:")
        self.csv_entry = ttk.Entry(csv_frame, textvariable=self.csv_path_var, width=30)
        self.csv_button = ttk.Button(csv_frame, text="Browse...", command=self.browse_csv)
        self.load_csv_button = ttk.Button(csv_frame, text="Load CSV", command=self.load_csv)

        # Layout widgets
        csv_label.pack(side=tk.LEFT)
        self.csv_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.csv_button.pack(side=tk.LEFT)
        self.load_csv_button.pack(side=tk.LEFT, padx=5)

        # Pack the frame
        csv_frame.pack(fill=tk.X, pady=5)

    def load_csv(self):
        """Load nicknames from CSV file."""
        if not self.csv_path_var.get():
            self._update_status("Error: No CSV file selected", "error")
            return

        # Try to load from CSV
        if self.nickname_manager.load_csv(self.csv_path_var.get()):
            self._update_status("Loaded nicknames from CSV", "connected")
            self.using_database = False

            # Auto-start monitoring if connected and not already started
            if self.connected_click_pid and not self.monitoring:
                self.start_monitoring()
        else:
            self._update_status("Failed to load from CSV", "error")

    def load_from_database(self):
        """Load nicknames directly from the CLICK database."""
        if not self.connected_click_pid:
            self._update_status("Error: Not connected to Click instance", "error")
            return

        # Clear the CSV path to indicate we're using the database
        self.csv_path_var.set("")

        # Try to load from database
        success = self.nickname_manager.load_from_database(
            click_pid=self.connected_click_pid,
            click_hwnd=self.detector.get_window_handle(self.connected_click_pid),
        )

        if success:
            self._update_status("Loaded nicknames from database", "connected")
            self.using_database = True

            # Gray out the CSV controls since we're using the database
            self._update_csv_controls_state()

            # Auto-start monitoring if not already started
            if not self.monitoring:
                self.start_monitoring()
        else:
            self._update_status("Failed to load from database", "error")
            self.using_database = False
            self._update_csv_controls_state()

    def _update_csv_controls_state(self):
        """Update the state of CSV controls based on database usage."""
        state = "disabled" if self.using_database else "normal"
        self.csv_entry.configure(state=state)
        self.csv_button.configure(state=state)
        self.load_csv_button.configure(state=state)

    def create_click_instances_section(self, parent):
        """Create the Click.exe instances section."""
        instances_frame = ttk.LabelFrame(parent, text="Click PLC Instances")

        # Create list box for instances
        self.instances_listbox = tk.Listbox(instances_frame, height=8)
        self.instances_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Add scrollbar
        scrollbar = ttk.Scrollbar(
            instances_frame, orient="vertical", command=self.instances_listbox.yview
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.instances_listbox.configure(yscrollcommand=scrollbar.set)

        # Buttons frame
        buttons_frame = ttk.Frame(instances_frame)

        # Create buttons
        refresh_button = ttk.Button(
            buttons_frame, text="Refresh", command=self.refresh_click_instances
        )
        connect_button = ttk.Button(buttons_frame, text="Connect", command=self.connect_to_selected)

        # Layout buttons
        refresh_button.pack(side=tk.LEFT, padx=5, pady=5)
        connect_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Pack buttons frame
        buttons_frame.pack(fill=tk.X, padx=5, pady=5)

        # Pack the main frame
        instances_frame.pack(fill=tk.BOTH, expand=True, pady=10)

    def create_options_section(self, parent):
        """Create the options section."""
        options_frame = ttk.LabelFrame(parent, text="Search Options")

        # Search mode widgets
        filter_frame = ttk.Frame(options_frame)
        filter_label = ttk.Label(filter_frame, text="Filter Mode:")
        none_radio = ttk.Radiobutton(
            filter_frame, text="None", variable=self.search_var, value="none"
        )
        prefix_radio = ttk.Radiobutton(
            filter_frame, text="Prefix Only", variable=self.search_var, value="prefix"
        )
        contains_radio = ttk.Radiobutton(
            filter_frame, text="Contains", variable=self.search_var, value="contains"
        )
        fuzzy_radio = ttk.Radiobutton(
            filter_frame, text="Fuzzy Match", variable=self.search_var, value="fuzzy"
        )

        # Layout filter widgets
        filter_label.pack(side=tk.LEFT)
        none_radio.pack(side=tk.LEFT, padx=5)
        prefix_radio.pack(side=tk.LEFT, padx=5)
        contains_radio.pack(side=tk.LEFT, padx=5)
        fuzzy_radio.pack(side=tk.LEFT, padx=5)
        filter_frame.pack(fill=tk.X, pady=5)

        # Fuzzy threshold slider
        fuzzy_frame = ttk.Frame(options_frame)
        fuzzy_label = ttk.Label(fuzzy_frame, text="Fuzzy Threshold:")
        fuzzy_slider = ttk.Scale(
            fuzzy_frame,
            from_=30,
            to=90,
            orient=tk.HORIZONTAL,
            variable=self.fuzzy_threshold_var,
            command=self._update_threshold_display,  # Add callback to format the display
        )

        # Create a StringVar for formatted display
        self.threshold_display_var = tk.StringVar(value=str(self.fuzzy_threshold_var.get()))
        fuzzy_value_label = ttk.Label(fuzzy_frame, textvariable=self.threshold_display_var)

        # Layout fuzzy threshold widgets
        fuzzy_label.pack(side=tk.LEFT)
        fuzzy_slider.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        fuzzy_value_label.pack(side=tk.LEFT, padx=5)
        fuzzy_frame.pack(fill=tk.X, pady=5)

        # Pack the main frame
        options_frame.pack(fill=tk.X, pady=5)

    def _update_threshold_display(self, value):
        """Update the displayed threshold value to an integer."""
        # Convert to integer (this will round down)
        int_value = int(float(value))

        # Make sure it's a multiple of 5
        int_value = round(int_value / 5) * 5

        # Update both the display and the actual variable
        self.threshold_display_var.set(str(int_value))
        self.fuzzy_threshold_var.set(int_value)

    def create_status_section(self, parent):
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
        status_frame.pack(fill=tk.X, pady=10)

    def browse_csv(self):
        """Open file dialog to select CSV file."""
        filepath = filedialog.askopenfilename(
            title="Select Nickname CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if filepath:
            self.csv_path_var.set(filepath)

    def refresh_click_instances(self):
        """Refresh the list of running Click.exe instances."""
        # Clear current list
        self.instances_listbox.delete(0, tk.END)
        self.click_instances = []

        try:
            # Get all Click.exe instances from detector
            click_instances = self.detector.get_click_instances()

            if not click_instances:
                return

            # Update UI with instances
            self.click_instances = click_instances
            for _, _, filename in click_instances:
                self.instances_listbox.insert(tk.END, filename)

        except Exception as e:
            print(f"Error refreshing Click instances: {e}")
            self._update_status(f"Error: {e!s}", "error")

    def connect_to_selected(self):
        """Connect to the selected Click.exe instance."""
        selected_idx = self.instances_listbox.curselection()
        if not selected_idx:
            self._update_status("No Click instance selected", "error")
            return

        # Get the selected instance
        idx = selected_idx[0]
        if idx >= len(self.click_instances):
            self._update_status("Invalid selection", "error")
            return

        # Store the connected instance
        self.connected_click_pid = self.click_instances[idx][0]
        self.connected_click_title = self.click_instances[idx][1]
        self.connected_click_filename = self.click_instances[idx][2]

        # Update status
        self._update_status(f"Connected to {self.click_instances[idx][2]}", "connected")

        # Reset database usage flag when connecting to a new instance
        self.using_database = False
        self._update_csv_controls_state()

        # Try to load nicknames from database automatically
        self.load_from_database()

    def toggle_monitoring(self):
        """Start or stop monitoring."""
        if self.monitoring:
            self.stop_monitoring()
        else:
            self.start_monitoring()

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
            else:
                # Try loading from database
                if not self.nickname_manager.load_from_database(
                    click_pid=self.connected_click_pid,
                    click_hwnd=self.detector.get_window_handle(self.connected_click_pid),
                ):
                    self._update_status("Error: No nickname source available", "error")
                    return

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

        # Destroy popup if it exists
        if self.popup:
            self.popup.withdraw()
            self.popup = None

        self._update_status("Monitoring stopped", "status")
        self.start_button.configure(text="Start")

    def _update_status(self, message, style="normal"):
        """Update status message with appropriate style."""
        self.status_var.set(message)
        if style == "error":
            self.status_label.configure(style="Error.TLabel")
        elif style == "connected":
            self.status_label.configure(style="Connected.TLabel")
        else:
            self.status_label.configure(style="Status.TLabel")

    def _monitor_task(self):
        """Monitor task that runs every 100ms using after."""
        if not self.monitoring:
            return

        # Check if connected Click.exe still exists
        if not self.detector.check_window_exists(self.connected_click_pid):
            self._update_status("Connected Click instance closed", "error")
            self.stop_monitoring()
            return

        # Skip detection if popup is visible and being managed
        if self.popup and self.popup.is_active():
            self.monitor_task_id = self.root.after(100, self._monitor_task)
            return

        # Check for popups belonging to our parent Click.exe
        child_info = self.detector.detect_child_window(self.connected_click_pid)
        if child_info:
            window_id, window_class, edit_control = child_info
            if not self.detector.field_has_text(edit_control, window_id):
                self._handle_popup_window(window_id, window_class, edit_control)
        else:
            # Hide popup if no valid popup window is detected
            if self.popup:
                self.popup.withdraw()

        # Schedule next check
        self.monitor_task_id = self.root.after(100, self._monitor_task)

    def _handle_popup_window(self, window_id, window_class, edit_control):
        """Handle the detected popup window by showing or updating the nickname popup."""
        try:
            # Create popup if it doesn't exist
            if not self.popup:
                self.popup = NicknamePopup(
                    self.root,
                    self.nickname_manager,
                    search_var=self.search_var,
                    fuzzy_threshold_var=self.fuzzy_threshold_var,
                    exclude_sc_sd_var=self.exclude_sc_sd_var,
                    exclude_nicknames_var=self.exclude_nicknames_var,
                )
                self.popup.set_target_window(window_id, window_class, edit_control)
            else:
                # Update target window info
                self.popup.set_target_window(window_id, window_class, edit_control)

            # Get allowed types for this window/control
            _, allowed_addresses = self.detector.update_window_info(window_class, edit_control)

            # Show the popup with filtered nicknames
            self.popup.show_combobox(allowed_addresses)

        except Exception as e:
            print(f"Error showing popup: {e}")

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
