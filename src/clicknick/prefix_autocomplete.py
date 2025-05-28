import tkinter as tk


class PrefixAutocomplete:
    """Handles autocomplete logic for text widgets."""

    def __init__(self, widget):
        self.widget = widget
        self._completion_list = []
        self._hits = []
        self._hit_index = 0
        self.position = 0
        self.finalized = False

    def set_completion_list(self, completion_list):
        """Set the list of completion options."""
        self._completion_list = completion_list

    def _autocomplete(self, delta: int = 0):
        """Perform autocompletion on the widget based on the current input."""
        if delta:
            # Delete text from current position to end
            self.widget.delete(self.position, tk.END)
        else:
            # Set the position to the length of the current input text
            self.position = len(self.widget.get())

            prefix = self.widget.get().lower()

            hits = [
                element
                for element in self._completion_list
                if str(element).lower().startswith(prefix)
            ]

        if hits:
            closest_match = min(hits, key=lambda x: len(str(x)))
            closest_match_str = str(closest_match)
            if prefix != closest_match_str.lower():
                # Insert the closest match at the beginning, move the cursor to the end
                self.widget.delete(0, tk.END)
                self.widget.insert(0, closest_match_str)
                self.widget.icursor(len(closest_match_str))

                # Highlight the remaining text after the closest match
                self.widget.select_range(self.position, tk.END)

            if len(hits) == 1 and closest_match_str.lower() != prefix:
                # If there is only one hit and it's not equal to the lowercase prefix,
                # open dropdown
                # self.widget.event_generate("<Down>")
                # self.widget.event_generate("<<ComboboxSelected>>")
                pass

        else:
            # If there are no hits, move the cursor to the current position
            self.widget.icursor(self.position)

        return hits

    def autocomplete(self, delta: int = 0) -> None:
        """Perform autocompletion based on the current input."""
        self._hits = self._autocomplete(delta)
        self._hit_index = 0

    def reset(self) -> None:
        """Reset the autocomplete state."""
        self._hits = []
        self._hit_index = 0
        self.position = 0
        self.finalized = False

    def handle_keyrelease(self, event) -> None:
        """Handle key release event for autocompletion and navigation."""
        if event.keysym == "BackSpace":
            self.widget.delete(self.position, tk.END)
            # Position stays the same
        elif event.keysym == "Left":
            if self.position < self.widget.index(tk.END):
                self.widget.delete(self.position, tk.END)
            else:
                self.position -= 1
                self.widget.delete(self.position, tk.END)
        elif event.keysym == "Right":
            self.position = self.widget.index(tk.END)
        elif event.keysym == "Return":
            self.widget.icursor(tk.END)
            self.widget.selection_clear()
            return
        elif len(event.keysym) == 1 or event.char == "_":
            self.autocomplete()
