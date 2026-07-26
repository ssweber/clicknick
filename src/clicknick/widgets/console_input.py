"""Slot-aware console input with autocomplete for the pyrung DAP console.

Extends ``ttk.Combobox`` and reuses ``DropdownManager`` / ``ComboboxTCLManager``
from :mod:`nickname_combobox`.  Delegates completion logic to
:class:`~clicknick.services.console_completer.ConsoleCompleter`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from .nickname_combobox import ComboboxTCLManager, DropdownManager

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..services.console_completer import ConsoleCompleter

_MAX_HISTORY = 200


class ConsoleInput(ttk.Combobox):
    """Smart input widget with slot-aware autocomplete."""

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _push_history(self, command: str) -> None:
        if not self._history or self._history[-1] != command:
            self._history.append(command)
            if len(self._history) > _MAX_HISTORY:
                self._history.pop(0)
        self._history_idx = len(self._history)

    def _set_text(self, text: str) -> None:
        self.delete(0, tk.END)
        self.insert(0, text)
        self.selection_clear()
        self.icursor(tk.END)

    def _history_prev(self) -> None:
        if not self._history:
            return
        self._history_idx = max(0, self._history_idx - 1)
        self._set_text(self._history[self._history_idx])

    def _history_next(self) -> None:
        if not self._history:
            return
        self._history_idx = min(len(self._history), self._history_idx + 1)
        if self._history_idx == len(self._history):
            self._set_text("")
        else:
            self._set_text(self._history[self._history_idx])

    # ------------------------------------------------------------------
    # Completion logic
    # ------------------------------------------------------------------

    def _update_completions(self, event: tk.Event | None = None) -> None:  # type: ignore[type-arg]
        text = self.get()
        cursor = self.index(tk.INSERT)

        result = self._completer.complete(text, cursor, self._tag_provider)

        self._pre_token = text[: result.token_start]
        self._post_token = text[result.token_end :]

        has_prefix = result.token_start < result.token_end

        if result.candidates and has_prefix:
            self["values"] = result.candidates
            if self._dropdown.is_dropdown_open():
                self._dropdown.update_listbox_directly(result.candidates)
            elif event and (
                (event.char and event.char.isprintable()) or event.keysym == "BackSpace"
            ):
                self._dropdown.open_dropdown_keep_focus()
        else:
            self._dropdown.hide_dropdown()

    # ------------------------------------------------------------------
    # Key event handlers
    # ------------------------------------------------------------------

    def _on_key_release(self, event: tk.Event) -> str | None:  # type: ignore[type-arg]
        if event.keysym in (
            "Return",
            "Up",
            "Down",
            "Tab",
            "Escape",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
        ):
            return

        self._update_completions(event)
        return "break"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _do_submit(self, text: str) -> None:
        self._push_history(text)
        self._set_text("")
        self._on_submit(text)

    def _on_return(self, event: tk.Event) -> str:  # type: ignore[type-arg]
        self._dropdown.hide_dropdown()
        text = self.get().strip()
        if text:
            self._do_submit(text)
        return "break"

    def _on_up(self, event: tk.Event) -> str | None:  # type: ignore[type-arg]
        if self._dropdown.is_dropdown_open():
            if self.focus_get() == self:
                self._dropdown.transfer_focus_to_listbox("up")
                return "break"
            return None
        self._history_prev()
        return "break"

    def _on_down(self, event: tk.Event) -> str | None:  # type: ignore[type-arg]
        if self._dropdown.is_dropdown_open():
            if self.focus_get() == self:
                self._dropdown.transfer_focus_to_listbox("down")
                return "break"
            return None
        self._history_next()
        return "break"

    def _accept_completion(self, selected: str) -> None:
        """Replace the current token with *selected* and advance cursor."""
        self._dropdown.hide_dropdown()

        new_text = self._pre_token + selected
        suffix = self._post_token
        if not suffix:
            new_text += " "
        else:
            new_text += suffix

        self._set_text(new_text)
        cursor = len(self._pre_token) + len(selected) + (1 if not suffix else 0)
        self.icursor(cursor)

    def _on_tab(self, event: tk.Event) -> str:  # type: ignore[type-arg]
        highlighted = self._dropdown.get_highlighted_item()
        if highlighted and self._dropdown.is_dropdown_open():
            self._accept_completion(highlighted)
        return "break"

    def _on_escape(self, event: tk.Event) -> str:  # type: ignore[type-arg]
        if self._dropdown.is_dropdown_open():
            self._dropdown.hide_dropdown()
        return "break"

    def _on_combobox_selected(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        selected = self.get()
        self._accept_completion(selected)

    # ------------------------------------------------------------------
    # Right-click edit menu
    # ------------------------------------------------------------------

    def _is_editable(self) -> bool:
        return str(self.cget("state")) != "disabled"

    def _clipboard_has_text(self) -> bool:
        try:
            return bool(self.clipboard_get())
        except tk.TclError:
            return False

    def _edit_event(self, virtual: str) -> None:
        """Fire a Tk edit virtual event, refreshing completions afterwards."""
        self.event_generate(virtual)
        self.after_idle(self._update_completions)

    def _select_all(self) -> None:
        self.select_range(0, tk.END)
        self.icursor(tk.END)

    def _build_edit_menu(self) -> tk.Menu:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Cut", command=lambda: self._edit_event("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: self._edit_event("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: self._edit_event("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Select All", command=self._select_all)
        return menu

    def _on_right_click(self, event: tk.Event) -> str:  # type: ignore[type-arg]
        self._dropdown.hide_dropdown()
        if self._is_editable():
            self.focus_set()

        editable = self._is_editable()
        has_selection = self.selection_present()
        menu = self._edit_menu
        menu.entryconfigure("Cut", state="normal" if editable and has_selection else "disabled")
        menu.entryconfigure("Copy", state="normal" if has_selection else "disabled")
        menu.entryconfigure(
            "Paste", state="normal" if editable and self._clipboard_has_text() else "disabled"
        )
        menu.entryconfigure("Select All", state="normal" if self.get() else "disabled")

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def __init__(
        self,
        parent: tk.Widget,
        *,
        completer: ConsoleCompleter,
        tag_provider: Callable[[str], list[str]],
        on_submit: Callable[[str], None],
        **kwargs,
    ) -> None:
        ComboboxTCLManager.setup_tcl_if_needed(parent)
        super().__init__(parent, **kwargs)

        self._completer = completer
        self._tag_provider = tag_provider
        self._on_submit = on_submit
        self._dropdown = DropdownManager(self)

        self._history: list[str] = []
        self._history_idx: int = 0

        self._pre_token: str = ""
        self._post_token: str = ""

        self._edit_menu = self._build_edit_menu()

        self.bind("<Button-3>", self._on_right_click)
        self.bind("<KeyRelease>", self._on_key_release)
        self.bind("<KeyPress-Return>", self._on_return)
        self.bind("<KeyPress-Up>", self._on_up)
        self.bind("<KeyPress-Down>", self._on_down)
        self.bind("<KeyPress-Tab>", self._on_tab)
        self.bind("<KeyPress-Escape>", self._on_escape)
        self.bind("<<ComboboxSelected>>", self._on_combobox_selected)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self) -> None:
        """Programmatic submit (e.g. from Send button)."""
        text = self.get().strip()
        if not text:
            return
        self._do_submit(text)

    def set_busy(self, busy: bool) -> None:
        self.configure(state="disabled" if busy else "normal")
        if not busy:
            self.focus_set()
