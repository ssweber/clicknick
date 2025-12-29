import tkinter as tk


class FloatingTooltip(tk.Toplevel):
    """A floating tooltip window that appears to the right of the combobox."""

    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        # Add this line to prevent the tooltip from taking focus
        self.attributes("-disabled", True)
        self.withdraw()

        # Configure appearance
        self.configure(bg="#ffffe0", relief="solid", borderwidth=1)  # Light yellow background

        # Create label for tooltip text
        self.label = tk.Label(
            self,
            text="",
            bg="#ffffe0",
            fg="black",
            font=("Segoe UI", 9),
            justify="left",
            wraplength=300,
            padx=8,
            pady=4,
        )
        self.label.pack()

    def show_tooltip(self, text, x, y):
        """Show tooltip with given text at specified position."""
        if not text:
            self.hide_tooltip()
            return

        self.label.config(text=text)
        self.update_idletasks()  # Update to get accurate size

        # Get tooltip dimensions
        tooltip_width = self.winfo_reqwidth()
        tooltip_height = self.winfo_reqheight()

        # Adjust position to avoid screen edges
        screen_width = self.winfo_screenwidth()

        # Position above the input - subtract tooltip height from y coordinate
        y = y - tooltip_height

        # Adjust horizontal position if needed
        if x + tooltip_width > screen_width:
            x = screen_width - tooltip_width - 10

        # If tooltip would go off top of screen, show it below instead
        if y < 0:
            y = self.winfo_rooty() + self.winfo_height() + 10  # Below the combobox

        self.geometry(f"+{x}+{y}")
        self.deiconify()

    def hide_tooltip(self):
        """Hide the tooltip."""
        self.withdraw()
