"""Data session: the loaded address data and everything bound to it.

One home for "which store is current". The AddressStore, the Dataview model
built on it, and the editor windows showing it all belong to one DataSession.
CSV and database data are both a DataSession. Loading different data closes
this session (prompting about unsaved edits) and opens a new one, so no window
or model can keep pointing at a replaced store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import tkinter as tk

    from .data.address_store import AddressStore
    from .data.shared_dataview import SharedDataviewData


class EditorWindow(Protocol):
    """What DataSession needs from an editor window."""

    def close_without_prompt(self) -> None: ...


class DataviewWindow(EditorWindow, Protocol):
    def has_unsaved_changes(self) -> bool: ...

    def save_all(self) -> Any: ...


def _close_quietly(window: EditorWindow) -> None:
    try:
        window.close_without_prompt()
    except Exception:
        import traceback

        traceback.print_exc()


class DataSession:
    """Owns the current AddressStore and the windows and models bound to it."""

    def __init__(self, store: AddressStore) -> None:
        self.store = store
        self.dataview: SharedDataviewData | None = None
        self._editors: list[EditorWindow] = []
        self._dataview_window: DataviewWindow | None = None

    # -- Windows -------------------------------------------------------------

    @property
    def editors(self) -> tuple[EditorWindow, ...]:
        """Open Address Editor windows."""
        return tuple(self._editors)

    @property
    def dataview_window(self) -> DataviewWindow | None:
        """The open Dataview Editor window, if any (only one at a time)."""
        return self._dataview_window

    @property
    def has_open_windows(self) -> bool:
        return bool(self._editors) or self._dataview_window is not None

    def register_editor(self, window: EditorWindow) -> None:
        if window not in self._editors:
            self._editors.append(window)

    def unregister_editor(self, window: EditorWindow) -> None:
        if window in self._editors:
            self._editors.remove(window)

    def register_dataview_window(self, window: DataviewWindow) -> None:
        self._dataview_window = window

    def unregister_dataview_window(self, window: DataviewWindow) -> None:
        if self._dataview_window is window:
            self._dataview_window = None

    def _confirm_close(self, parent: tk.Misc | None) -> bool:
        from tkinter import messagebox

        # Editor windows are Tk Toplevels; the protocols only name what we call.
        window = self._dataview_window
        if window is not None and window.has_unsaved_changes():
            dataview_owner: Any = window
            answer = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes in Dataview Editor. Save before closing?",
                parent=dataview_owner,
            )
            if answer is None:
                return False
            if answer:
                window.save_all()

        if self.store.has_unsaved_changes():
            owner: Any = self._editors[0] if self._editors else parent
            answer = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved address changes. Save before closing?",
                parent=owner,
            )
            if answer is None:
                return False
            if answer:
                try:
                    self.store.save_all_changes()
                except Exception as exc:
                    messagebox.showerror(
                        "Save Error",
                        f"Failed to save changes: {exc}\n\nNothing was closed.",
                        parent=owner,
                    )
                    return False
        return True

    # -- Teardown ------------------------------------------------------------

    def close(self, parent: tk.Misc | None = None, *, prompt_save: bool = True) -> bool:
        """Close every window and stop monitoring the store.

        With prompt_save, unsaved Dataview and address edits are offered for
        saving first. Returns False, with nothing closed, if the user cancels
        or a save fails.
        """
        if prompt_save and not self._confirm_close(parent):
            return False
        self.force_close()
        return True

    def force_close(self) -> None:
        """Close every window without prompting and stop monitoring the store."""
        window = self._dataview_window
        self._dataview_window = None
        if window is not None:
            _close_quietly(window)
        for editor in list(self._editors):
            _close_quietly(editor)
        self._editors.clear()
        self.store.stop_file_monitoring()
