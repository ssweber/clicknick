"""Data session: the loaded address data and everything bound to it.

A DataSession is the one place that knows which store is current. The AddressStore, the
Dataview model built on it, and the editor windows that show it all belong to one
DataSession. CSV data and database data are both a DataSession. When you load different
data, ClickNick closes the current session, prompting about unsaved edits, and opens a
new one. No window or model can keep pointing at a replaced store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import tkinter as tk

    from .data.address_store import AddressStore
    from .data.shared_dataview import SharedDataviewData


class EditorWindow(Protocol):
    """What DataSession and the app need from an editor window."""

    def close_without_prompt(self) -> None: ...

    def refresh_title(self) -> None: ...

    def winfo_exists(self) -> bool | int: ...


class AddressEditor(EditorWindow, Protocol):
    def commit_open_cell_editor(self) -> bool:
        """Turn text typed in an open cell editor into an edit. Return False if it cannot commit."""
        ...


class DataviewWindow(EditorWindow, Protocol):
    def commit_open_cell_editor(self) -> bool:
        """Turn text typed in an open cell editor into an edit. Return False if it cannot commit."""
        ...

    def refresh_file_list(self) -> None: ...

    def has_unsaved_changes(self) -> bool: ...

    def save_all(self) -> bool: ...


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
        self._editors: list[AddressEditor] = []
        self._dataview_window: DataviewWindow | None = None

    # -- Windows -------------------------------------------------------------

    @property
    def editors(self) -> tuple[AddressEditor, ...]:
        """Return the open Address Editor windows."""
        return tuple(self._editors)

    @property
    def dataview_window(self) -> DataviewWindow | None:
        """Return the open Dataview Editor window, or None. Only one can be open at a time."""
        return self._dataview_window

    @property
    def has_open_windows(self) -> bool:
        return bool(self._editors) or self._dataview_window is not None

    def register_editor(self, window: AddressEditor) -> None:
        if window not in self._editors:
            self._editors.append(window)

    def unregister_editor(self, window: AddressEditor) -> None:
        if window in self._editors:
            self._editors.remove(window)

    def register_dataview_window(self, window: DataviewWindow) -> None:
        self._dataview_window = window

    def unregister_dataview_window(self, window: DataviewWindow) -> None:
        if self._dataview_window is window:
            self._dataview_window = None

    def commit_open_cell_editors(self) -> bool:
        """Turn text still typed in Address Editor cells into edits. Return False if a cell fails.

        This method tries every editor, even after one fails.
        """
        committed = [editor.commit_open_cell_editor() for editor in self._editors]
        return all(committed)

    def _confirm_close(self, parent: tk.Misc | None) -> bool:
        from tkinter import messagebox

        # Text still in a cell editor is an edit. A cell that cannot commit stops the close.
        if not self.commit_open_cell_editors():
            return False

        # Editor windows are Tk Toplevels. The protocols only name the methods we call.
        window = self._dataview_window
        if window is not None and not window.commit_open_cell_editor():
            return False
        if window is not None and window.has_unsaved_changes():
            dataview_owner: Any = window
            answer = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes in the Data View Editor. Save before closing?",
                parent=dataview_owner,
            )
            if answer is None:
                return False
            # A cancelled or failed save (the window says why) closes nothing
            if answer and not window.save_all():
                return False

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

        With prompt_save, ClickNick first offers to save unsaved Dataview and address edits.
        If the user cancels or a save fails, this method closes nothing and returns False.
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
