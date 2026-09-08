import platform
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from tkinter import filedialog, ttk

from ..data.data_source import convert_mdb_csv_to_user_csv
from ..utils.mdb_shared import (
    get_available_access_drivers,
    get_database_backend,
    probe_database_connection,
)
from ..utils.win32_utils import WIN32


def open_url(url):
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception as e:
        print(f"Could not open browser: {e}")


def _installed_version(package: str) -> str:
    """Return one installed package version for support diagnostics."""
    try:
        return package_version(package)
    except PackageNotFoundError:
        return "Not installed"


def _build_system_info(app_version: str, access_drivers: list[str]) -> str:
    """Build the diagnostic text shown and copied by About ClickNick."""
    odbc_info = ", ".join(access_drivers) if access_drivers else "Not installed (optional)"
    return (
        f"ClickNick: {app_version}\n"
        f"pyrung: {_installed_version('pyrung')}\n"
        f"Python: {sys.version.split()[0]}\n"
        f"Windows: {platform.system()} {platform.release()}\n"
        f"Architecture: {platform.machine()}\n"
        f"Tkinter: {tk.TkVersion}\n"
        f"MS Access ODBC: {odbc_info}\n"
        f"Database selection: {get_database_backend()}\n"
        f"Python full: {sys.version}\n"
        f"Platform details: {platform.platform()}"
    )


class AboutDialog:
    def __init__(self, parent, version, db_path=None):
        self.parent = parent
        self.version = version
        self.db_path = db_path

        self.create_window()

    def create_window(self):
        self.window = tk.Toplevel(self.parent)
        self.window.title("About ClickNick")
        self.window.resizable(False, False)
        self.window.grab_set()
        self.window.transient(self.parent)

        main_frame = ttk.Frame(self.window, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Get dynamic version
        app_version = self.version

        # App info
        ttk.Label(main_frame, text="ClickNick", font=("Arial", 18, "bold")).pack(pady=(0, 5))
        ttk.Label(main_frame, text=f"Version {app_version}", font=("Arial", 12)).pack()
        ttk.Label(main_frame, text="Better tools for AutomationDirect CLICK PLCs").pack(
            pady=(0, 15)
        )

        # Description
        desc_text = (
            "Write, check, test, troubleshoot, and maintain CLICK ladder\n"
            "without replacing CLICK Programming Software.\n\n"
            "Nickname autocomplete and project-aware editing\n"
            "Static program checks and offline simulation\n"
            "Persistent workspaces with reviewed ladder changes\n\n"
            "CLICK stays CLICK: proposed changes are reviewed and only become\n"
            "part of the project when you save them in CLICK."
        )
        ttk.Label(main_frame, text=desc_text, justify=tk.CENTER).pack(pady=(0, 15))

        # System Information as multi-line text widget
        info_frame = ttk.LabelFrame(main_frame, text="System Information", padding="10")

        # Create text widget with scrollbar
        text_frame = ttk.Frame(info_frame)

        info_text = tk.Text(
            text_frame,
            height=8,
            width=50,
            wrap=tk.WORD,
            font=("Courier New", 9),
            bg="white",
            relief=tk.SUNKEN,
            bd=1,
        )
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=info_text.yview)
        info_text.configure(yscrollcommand=scrollbar.set)

        access_drivers = get_available_access_drivers()
        system_info_display = _build_system_info(app_version, access_drivers)

        info_text.insert(tk.END, system_info_display)
        info_text.config(state=tk.DISABLED)  # Make it read-only

        # Pack text widget and scrollbar
        info_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_frame.pack(fill=tk.BOTH, expand=True)

        info_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # Copy system info button
        def copy_system_info():
            """Copy version and system information to clipboard."""
            try:
                WIN32.set_clipboard(system_info_display)
            except Exception:
                self.window.clipboard_clear()
                self.window.clipboard_append(system_info_display)
            copy_btn.config(text="Copied")
            self.window.after(2000, lambda: copy_btn.config(text="Copy System Info"))

        copy_btn = ttk.Button(main_frame, text="Copy System Info", command=copy_system_info)
        copy_btn.pack(pady=(0, 15))

        connection_status = tk.StringVar(value="Test reads the address table without changing it.")

        def test_connection():
            if get_database_backend() == "none":
                connection_status.set(probe_database_connection(None).message)
                return
            path = self.db_path or filedialog.askopenfilename(
                parent=self.window,
                title="Choose CLICK Database",
                filetypes=[("Access database", "*.mdb")],
            )
            if not path:
                return
            test_btn.state(["disabled"])
            connection_status.set("Testing connection...")
            results = queue.Queue()
            threading.Thread(
                target=lambda: results.put(probe_database_connection(path)), daemon=True
            ).start()

            def finish():
                nonlocal system_info_display
                if not self.window.winfo_exists():
                    return
                try:
                    result = results.get_nowait()
                except queue.Empty:
                    self.window.after(100, finish)
                    return
                test_btn.state(["!disabled"])
                connection_status.set(result.message)
                system_info_display = _build_system_info(app_version, access_drivers) + (
                    "\nDatabase test: " + result.message
                )
                info_text.config(state=tk.NORMAL)
                info_text.delete("1.0", tk.END)
                info_text.insert(tk.END, system_info_display)
                info_text.config(state=tk.DISABLED)

            self.window.after(100, finish)

        test_btn = ttk.Button(main_frame, text="Test Connection", command=test_connection)
        test_btn.pack(pady=(0, 5))
        ttk.Label(main_frame, textvariable=connection_status, wraplength=450).pack(pady=(0, 15))

        # Links
        links_frame = ttk.LabelFrame(main_frame, text="Links & Support", padding="10")

        github_btn = ttk.Button(
            links_frame,
            text="GitHub Repository",
            command=lambda: open_url("https://github.com/ssweber/clicknick"),
        )
        github_btn.pack(fill=tk.X, pady=2)

        issues_btn = ttk.Button(
            links_frame,
            text="Report an Issue",
            command=lambda: open_url("https://github.com/ssweber/clicknick/issues"),
        )
        issues_btn.pack(fill=tk.X, pady=2)

        # Add ODBC driver help link if drivers are missing
        if not access_drivers:
            odbc_help_btn = ttk.Button(
                links_frame,
                text="Database Connection Help",
                command=lambda: open_url("https://pyrung.com/clicknick/help/#database-connection"),
            )
            odbc_help_btn.pack(fill=tk.X, pady=2)

        links_frame.pack(fill=tk.X, pady=(0, 15))

        # Copyright and license
        copyright_frame = ttk.Frame(main_frame)
        ttk.Label(
            copyright_frame, text=f"© {datetime.now().year} ssweber", font=("Arial", 9)
        ).pack()
        ttk.Label(copyright_frame, text="Licensed under AGPL-3.0 License", font=("Arial", 9)).pack()
        copyright_frame.pack(pady=(0, 15))

        # Close button
        close_btn = ttk.Button(main_frame, text="Close", command=self.window.destroy)
        close_btn.pack(pady=10)
        close_btn.focus_set()


class OdbcWarningDialog:
    def __init__(self, parent):
        self.parent = parent
        self.create_window()

    def create_window(self):
        self.window = tk.Toplevel(self.parent)
        self.window.title(
            "CSV Mode" if get_database_backend() == "none" else "Database Connection Unavailable"
        )
        self.window.resizable(False, False)
        self.window.grab_set()
        self.window.transient(self.parent)

        message = (
            "The selected database connection is unavailable.\n\n"
            "You can load nicknames from a CSV file.\n\n"
            "Use Help > About ClickNick > Test Connection for details."
        )

        # Center the window
        self.window.geometry(f"+{self.parent.winfo_rootx() + 50}+{self.parent.winfo_rooty() + 50}")

        main_frame = ttk.Frame(self.window, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Warning icon and title
        title_frame = ttk.Frame(main_frame)
        ttk.Label(title_frame, text="⚠️", font=("Arial", 24)).pack(side=tk.LEFT)
        ttk.Label(
            title_frame,
            text="CSV Mode"
            if get_database_backend() == "none"
            else "Database Connection Unavailable",
            font=("Arial", 14, "bold"),
        ).pack(side=tk.LEFT, padx=(10, 0))
        title_frame.pack(pady=(0, 15))

        # Message
        ttk.Label(main_frame, text=message, wraplength=450, justify=tk.LEFT).pack(pady=(0, 15))

        ttk.Button(
            main_frame,
            text="Connection Help",
            command=lambda: open_url("https://pyrung.com/clicknick/help/#database-connection"),
        ).pack(pady=(0, 15))

        # Close button
        ttk.Button(main_frame, text="OK", command=self.window.destroy).pack()

        # Focus the window
        self.window.focus_set()


class CsvFallbackDialog:
    """Offer a copy of Address.csv when using CSV mode."""

    def __init__(self, parent, source_csv_path: Path, default_filename: str = "Address.csv"):
        self.parent = parent
        self.source_csv_path = source_csv_path
        self.default_filename = default_filename
        self.saved_path: str | None = None

        self.create_window()

    def _on_save_copy(self):
        """Handle Save Copy button - open Save As dialog and convert file."""
        # Get user's Documents folder as default
        try:
            import os

            documents = Path(os.path.expanduser("~/Documents"))
            if not documents.exists():
                documents = Path.home()
        except Exception:
            documents = Path.home()

        # Open Save As dialog
        dest_path = filedialog.asksaveasfilename(
            parent=self.window,
            title="Save Address CSV Copy",
            initialdir=str(documents),
            initialfile=self.default_filename,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )

        if dest_path:
            try:
                # Convert MDB-format CSV to user-format CSV
                convert_mdb_csv_to_user_csv(str(self.source_csv_path), dest_path)
                self.saved_path = dest_path
                self.window.destroy()
            except Exception as e:
                # Show error message
                tk.messagebox.showerror(
                    "Error",
                    f"Failed to convert and save file:\n{e}",
                    parent=self.window,
                )

    def _on_cancel(self):
        """Handle Cancel button."""
        self.saved_path = None
        self.window.destroy()

    def create_window(self):
        self.window = tk.Toplevel(self.parent)
        self.window.title(
            "CSV Mode" if get_database_backend() == "none" else "Database Connection Unavailable"
        )
        self.window.resizable(False, False)
        self.window.grab_set()
        self.window.transient(self.parent)

        # Center the window
        self.window.geometry(f"+{self.parent.winfo_rootx() + 50}+{self.parent.winfo_rooty() + 50}")

        main_frame = ttk.Frame(self.window, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Warning icon and title
        title_frame = ttk.Frame(main_frame)
        ttk.Label(title_frame, text="⚠️", font=("Arial", 24)).pack(side=tk.LEFT)
        ttk.Label(
            title_frame,
            text="CSV Mode"
            if get_database_backend() == "none"
            else "Database Connection Unavailable",
            font=("Arial", 14, "bold"),
        ).pack(side=tk.LEFT, padx=(10, 0))
        title_frame.pack(pady=(0, 15))

        # Explanation
        intro_text = (
            "A project CSV file was found, but it cannot be used directly.\n"
            "You must save a copy to continue."
        )
        ttk.Label(main_frame, text=intro_text, wraplength=400, justify=tk.LEFT).pack(pady=(0, 15))

        # Warnings frame
        warnings_frame = ttk.LabelFrame(main_frame, text="Important", padding="10")

        warnings = [
            "• This file is generated when CLICK opens a project",
            "• Does NOT update with changes made in CLICK after load",
            "• Will be DELETED when CLICK closes",
        ]
        for warning in warnings:
            ttk.Label(warnings_frame, text=warning, wraplength=380, justify=tk.LEFT).pack(
                anchor=tk.W, pady=2
            )

        warnings_frame.pack(fill=tk.X, pady=(0, 15))

        # Buttons frame
        button_frame = ttk.Frame(main_frame)

        save_btn = ttk.Button(
            button_frame, text="Save Copy && Continue", command=self._on_save_copy
        )
        save_btn.pack(side=tk.LEFT, padx=(0, 10))

        cancel_btn = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_btn.pack(side=tk.LEFT, padx=(0, 10))

        help_btn = ttk.Button(
            button_frame,
            text="Connection Help",
            command=lambda: open_url("https://pyrung.com/clicknick/help/#database-connection"),
        )
        help_btn.pack(side=tk.LEFT)

        button_frame.pack(pady=(0, 10))

        # Focus save button
        save_btn.focus_set()

        # Make dialog modal - wait for it to close
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def show(self) -> str | None:
        """Show the dialog and return the saved path (or None if cancelled)."""
        self.window.wait_window()
        return self.saved_path
