"""Enhanced Custom ttk Notebook with close buttons.

Source: https://stackoverflow.com/a/39459376
Posted by Bryan Oakley, modified by community
License: CC BY-SA 4.0
Enhanced with features inspired by Thonny IDE (MIT License)

Added: middle-click close, right-click menu, keyboard shortcuts
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk


class CustomNotebook(ttk.Notebook):
    """A ttk Notebook with close buttons and enhanced interaction."""

    __initialized = False

    def __initialize_custom_style(self):
        style = ttk.Style()
        self.images = (
            tk.PhotoImage(
                "img_close",
                data="""
                R0lGODlhCAAIAMIBAAAAADs7O4+Pj9nZ2Ts7Ozs7Ozs7Ozs7OyH+EUNyZWF0ZWQg
                d2l0aCBHSU1QACH5BAEKAAQALAAAAAAIAAgAAAMVGDBEA0qNJyGw7AmxmuaZhWEU
                5kEJADs=
                """,
            ),
            tk.PhotoImage(
                "img_closeactive",
                data="""
                R0lGODlhCAAIAMIEAAAAAP/SAP/bNNnZ2cbGxsbGxsbGxsbGxiH5BAEKAAQALAAA
                AAAIAAgAAAMVGDBEA0qNJyGw7AmxmuaZhWEU5kEJADs=
                """,
            ),
            tk.PhotoImage(
                "img_closepressed",
                data="""
                R0lGODlhCAAIAMIEAAAAAOUqKv9mZtnZ2Ts7Ozs7Ozs7Ozs7OyH+EUNyZWF0ZWQg
                d2l0aCBHSU1QACH5BAEKAAQALAAAAAAIAAgAAAMVGDBEA0qNJyGw7AmxmuaZhWEU
                5kEJADs=
            """,
            ),
        )

        style.element_create(
            "close",
            "image",
            "img_close",
            ("active", "pressed", "!disabled", "img_closepressed"),
            ("active", "!disabled", "img_closeactive"),
            border=8,
            sticky="",
        )
        style.layout("CustomNotebook", [("CustomNotebook.client", {"sticky": "nswe"})])
        style.layout(
            "CustomNotebook.Tab",
            [
                (
                    "CustomNotebook.tab",
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "CustomNotebook.padding",
                                {
                                    "side": "top",
                                    "sticky": "nswe",
                                    "children": [
                                        (
                                            "CustomNotebook.focus",
                                            {
                                                "side": "top",
                                                "sticky": "nswe",
                                                "children": [
                                                    (
                                                        "CustomNotebook.label",
                                                        {"side": "left", "sticky": ""},
                                                    ),
                                                    (
                                                        "CustomNotebook.close",
                                                        {"side": "left", "sticky": ""},
                                                    ),
                                                ],
                                            },
                                        )
                                    ],
                                },
                            )
                        ],
                    },
                )
            ],
        )

    def _on_right_click(self, event):
        """Handle right-click on tab."""
        element = self.identify(event.x, event.y)
        if "label" in element or "close" in element:
            # Store which tab was clicked
            self._clicked_tab_index = self.index("@%d,%d" % (event.x, event.y))
            self.context_menu.post(event.x_root, event.y_root)
            return "break"

    def _try_close_tab(self, index: int) -> bool:
        """Centralized tab closing with callback support."""
        if self._on_close_callback:
            if not self._on_close_callback(index):
                # Close was cancelled
                return False

        self.forget(index)
        self.event_generate("<<NotebookTabClosed>>")
        return True

    def _on_middle_click(self, event):
        """Handle middle-click to close tab."""
        element = self.identify(event.x, event.y)
        if "label" in element or "close" in element:
            index = self.index("@%d,%d" % (event.x, event.y))
            self._try_close_tab(index)
            return "break"

    def _close_from_menu(self):
        """Close the tab that was right-clicked."""
        if hasattr(self, '_clicked_tab_index'):
            self._try_close_tab(self._clicked_tab_index)

    def _close_other_tabs(self):
        """Close all tabs except the right-clicked one."""
        if not hasattr(self, '_clicked_tab_index'):
            return

        current = self._clicked_tab_index
        # Close from right to left to avoid index shifting issues
        for i in range(len(self.tabs()) - 1, -1, -1):
            if i != current:
                # Check if close is allowed for each tab
                if not self._try_close_tab(i):
                    # If any tab refuses to close, stop (user probably wants to review)
                    break

    def _close_all_tabs(self):
        """Close all tabs."""
        # Close from right to left to avoid index shifting issues
        for i in range(len(self.tabs()) - 1, -1, -1):
            if not self._try_close_tab(i):
                # If any tab refuses to close, stop
                break

    def _create_context_menu(self):
        """Create right-click menu for tabs."""
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="Close", command=self._close_from_menu)
        self.context_menu.add_command(label="Close Others", command=self._close_other_tabs)
        self.context_menu.add_command(label="Close All", command=self._close_all_tabs)

        self.bind("<ButtonPress-3>", self._on_right_click, True)  # Right-click
        self.bind("<ButtonPress-2>", self._on_middle_click, True)  # Middle-click

    def _close_current_tab(self, event=None):
        """Close current tab (Ctrl+W)."""
        if len(self.tabs()) > 0:
            self._try_close_tab(self.index(self.select()))
            return "break"

    def _bind_keyboard_shortcuts(self):
        """Add keyboard shortcuts for tab navigation and closing."""
        self.bind_all("<Control-w>", self._close_current_tab)

    def __init__(self, *args, **kwargs):
        # Extract our custom callback before passing to parent
        self._on_close_callback: Callable[[int], bool] | None = kwargs.pop(
            "on_close_callback", None
        )

        if not CustomNotebook.__initialized:
            self.__initialize_custom_style()
            CustomNotebook.__initialized = True

        kwargs["style"] = "CustomNotebook"
        ttk.Notebook.__init__(self, *args, **kwargs)

        self._active = None

        self.bind("<ButtonPress-1>", self.on_close_press, True)
        self.bind("<ButtonRelease-1>", self.on_close_release)

        # Add right-click context menu
        self._create_context_menu()

        # Add keyboard shortcuts
        self._bind_keyboard_shortcuts()

    def set_close_callback(self, callback: Callable[[int], bool] | None) -> None:
        """Set the callback for tab close."""
        self._on_close_callback = callback

    def on_close_press(self, event):
        """Called when the button is pressed over the close button."""
        element = self.identify(event.x, event.y)

        if "close" in element:
            index = self.index("@%d,%d" % (event.x, event.y))
            self.state(["pressed"])
            self._active = index
            return "break"

    def on_close_release(self, event):
        """Called when the button is released."""
        if not self.instate(["pressed"]):
            return

        element = self.identify(event.x, event.y)
        if "close" not in element:
            # user moved the mouse off of the close button
            return

        index = self.index("@%d,%d" % (event.x, event.y))

        if self._active == index:
            self._try_close_tab(index)

        self.state(["!pressed"])
        self._active = None
