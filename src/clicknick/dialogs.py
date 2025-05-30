import platform
import sys
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from .shared_ahk import AHK


def open_url(url):
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception as e:
        print(f"Could not open browser: {e}")


class AboutDialog:
    def __init__(self, parent, version, nickname_manager):
        self.parent = parent
        self.version = version
        self.nickname_manager = nickname_manager

        self.create_window()

    def create_window(self):
        self.window = tk.Toplevel(self.parent)
        self.window.title("About ClickNick")
        self.window.geometry("500x750")
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
        ttk.Label(
            main_frame, text="Intelligent nickname overlay for Click PLC", font=("Arial", 10)
        ).pack(pady=(0, 15))

        # Description
        desc_text = (
            "Automatically detects Click PLC popup windows and provides\n"
            "nickname suggestions with filtering."
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

        # Get ODBC driver information
        access_drivers = self.nickname_manager.get_available_access_drivers()
        if access_drivers:
            odbc_info = f"MS Access ODBC: {', '.join(access_drivers)}"
        else:
            odbc_info = "MS Access ODBC: Not installed ⚠️"

        # Populate the text widget with system information
        system_info_display = (
            f"Python: {sys.version.split()[0]}\n"
            f"Platform: {platform.system()} {platform.release()}\n"
            f"Tkinter: {tk.TkVersion}\n"
            f"Architecture: {platform.machine()}\n"
            f"{odbc_info}\n"
            f"Python Full: {sys.version}\n"
            f"Platform Details: {platform.platform()}"
        )

        info_text.insert(tk.END, system_info_display)
        info_text.config(state=tk.DISABLED)  # Make it read-only

        # Pack text widget and scrollbar
        info_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_frame.pack(fill=tk.BOTH, expand=True)

        info_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # Copy system info button
        def copy_system_info():
            """Copy version and system information to clipboard using AHK."""
            try:
                # Get ODBC driver information
                access_drivers = self.nickname_manager.get_available_access_drivers()
                if access_drivers:
                    odbc_info = f"MS Access ODBC Drivers: {', '.join(access_drivers)}"
                else:
                    odbc_info = "MS Access ODBC Drivers: None installed"

                system_info = (
                    f"ClickNick Version: {app_version}\n"
                    f"Python: {sys.version.split()[0]}\n"
                    f"Platform: {platform.system()} {platform.release()}\n"
                    f"Tkinter: {tk.TkVersion}\n"
                    f"Architecture: {platform.machine()}\n"
                    f"{odbc_info}\n"
                    f"Python Full Version: {sys.version}\n"
                    f"Platform Details: {platform.platform()}"
                )

                # Use AHK to set clipboard
                AHK.set("Clipboard", system_info)

                # Visual feedback - temporarily change button text
                copy_btn.config(text="✓ Copied!")
                self.window.after(2000, lambda: copy_btn.config(text="📋 Copy System Info"))

            except Exception as e:
                print(f"Error copying system info: {e}")
                # Fallback to tkinter clipboard if AHK fails
                self.window.clipboard_clear()
                self.window.clipboard_append(system_info)

        copy_btn = ttk.Button(main_frame, text="📋 Copy System Info", command=copy_system_info)
        copy_btn.pack(pady=(0, 15))

        # Links
        links_frame = ttk.LabelFrame(main_frame, text="Links & Support", padding="10")

        github_btn = ttk.Button(
            links_frame,
            text="🔗 GitHub Repository",
            command=lambda: open_url("https://github.com/ssweber/clicknick"),
        )
        github_btn.pack(fill=tk.X, pady=2)

        issues_btn = ttk.Button(
            links_frame,
            text="🐛 Report Issues",
            command=lambda: open_url("https://github.com/ssweber/clicknick/issues"),
        )
        issues_btn.pack(fill=tk.X, pady=2)

        # Add ODBC driver help link if drivers are missing
        if not access_drivers:
            odbc_help_btn = ttk.Button(
                links_frame,
                text="🔧 Install ODBC Drivers",
                command=lambda: open_url("https://github.com/ssweber/clicknick/issues/17"),
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
        self.window.title("ODBC Drivers Not Found")
        self.window.geometry("500x300")
        self.window.resizable(False, False)
        self.window.grab_set()
        self.window.transient(self.parent)

        message = (
            "Microsoft Access ODBC drivers are not installed on this system.\n\n"
            "Live nickname database functionality will be disabled. You can still use "
            "CSV files for nickname loading.\n\n"
            "For help installing the required drivers, please see our GitHub issue:"
        )

        # Center the window
        self.window.geometry(f"+{self.parent.winfo_rootx() + 50}+{self.parent.winfo_rooty() + 50}")

        main_frame = ttk.Frame(self.window, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Warning icon and title
        title_frame = ttk.Frame(main_frame)
        ttk.Label(title_frame, text="⚠️", font=("Arial", 24)).pack(side=tk.LEFT)
        ttk.Label(title_frame, text="ODBC Drivers Not Found", font=("Arial", 14, "bold")).pack(
            side=tk.LEFT, padx=(10, 0)
        )
        title_frame.pack(pady=(0, 15))

        # Message
        ttk.Label(main_frame, text=message, wraplength=450, justify=tk.LEFT).pack(pady=(0, 15))

        # GitHub link button
        github_issue_url = (
            "https://github.com/ssweber/clicknick/issues/17"  # Update with actual issue number
        )

        ttk.Button(
            main_frame,
            text="🔗 View Installation Guide",
            command=lambda: open_url(github_issue_url),
        ).pack(pady=(0, 15))

        # Close button
        ttk.Button(main_frame, text="OK", command=self.window.destroy).pack()

        # Focus the window
        self.window.focus_set()
