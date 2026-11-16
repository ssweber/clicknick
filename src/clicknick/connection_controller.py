"""Connecting to CLICK windows, and following the connected one.

``ConnectionController`` lists the CLICK windows, connects to one (opening its
``ConnectionSession`` and loading its database, or offering the CSV fallback),
follows a project change, notices the window closing, and shows the autocomplete
popup while monitoring is on. The facts it changes keep their homes on the app:
the session in ``ClickNickApp._session``, the data in ``ClickNickApp._data``
(through ``_open_data`` and ``_close_data``). It keeps only the window list and
the user's monitoring choice.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from tkinter import messagebox
from typing import TYPE_CHECKING, Protocol

from .connection_session import ClickConnection
from .data.address_store import AddressStore
from .detection.window_detector import ClickInstance, ClickWindowDetector
from .utils.mdb_shared import find_fallback_csv
from .views.dialogs import CsvFallbackDialog
from .views.overlay import Overlay

if TYPE_CHECKING:
    import tkinter as tk
    from collections.abc import Callable
    from tkinter import ttk

    from .connection_session import ConnectionSession
    from .data.nickname_manager import NicknameManager
    from .data_session import DataSession


class ConnectionHost(Protocol):
    """What ConnectionController uses of the app (``ClickNickApp``)."""

    root: tk.Tk
    # The connected session and the loaded data: their one home (assigning
    # either refreshes the main window)
    _session: ConnectionSession | None
    _data: DataSession | None
    nickname_manager: NicknameManager
    detector: ClickWindowDetector
    # The ClickPLC Windows section
    instances_combobox: ttk.Combobox
    selected_instance_var: tk.StringVar
    start_button: ttk.Button

    @property
    def _click(self) -> ClickConnection | None: ...

    @property
    def using_database(self) -> bool: ...

    def _open_data(
        self, store: AddressStore, *, still_wanted: Callable[[], bool] | None = None
    ) -> bool: ...

    def _close_data(self, *, prompt_save: bool) -> bool: ...

    def _open_dataview_editor(self) -> None: ...

    def _start_analysis_build(self) -> None: ...

    def _update_status(self, message: str, style: str = "normal") -> None: ...

    def _show_main_window(self) -> None: ...

    def _show_odbc_warning(self) -> None: ...

    def _on_sync_status_changed(self, pending: int) -> None: ...

    def _on_build_finished(self) -> None: ...

    def _remove_stale_compare_copies(self, open_hwnds: set[int]) -> None: ...


class ConnectionController:
    """The connection lifecycle: list, connect, follow, watch, close."""

    def __init__(self, app: ConnectionHost) -> None:
        self._app = app
        # The CLICK windows the combobox lists (ClickInstance values)
        self.click_instances: list[ClickInstance] = []
        # Autocomplete popups on or off: only the user's Start/Stop, or a window
        # the user picks, changes it. The connection watch (_monitor_task) runs
        # whenever a CLICK window is connected, whatever this says.
        self.monitoring = True
        self._status_after_id = None
        self._odbc_warning_shown = False

    # -- The window list -----------------------------------------------------

    def _instance_labels(self) -> list[str]:
        """The combobox's label for each CLICK window: its filename, with the PID where
        two windows show the same filename."""
        counts = Counter(instance.filename for instance in self.click_instances)
        return [
            f"{instance.filename} (PID {instance.pid})"
            if counts[instance.filename] > 1
            else instance.filename
            for instance in self.click_instances
        ]

    def on_instance_selected(self, event=None):
        """Connect to the CLICK window picked in the combobox."""
        labels = self._instance_labels()
        selected_text = self._app.selected_instance_var.get()
        if selected_text not in labels:
            return
        instance = self.click_instances[labels.index(selected_text)]
        self.connect_to_instance(
            instance.pid, instance.title, instance.filename, instance.hwnd, user_picked=True
        )

    def _select_connected_instance(self) -> None:
        """Select the connected CLICK window in the combobox (nothing when none is)."""
        click = self._app._click
        label = ""
        if click is not None:
            for instance, text in zip(self.click_instances, self._instance_labels(), strict=True):
                if instance.hwnd == click.hwnd:
                    label = text
                    break
        self._app.selected_instance_var.set(label)

    def _show_instances(self, connected_title: str | None = None) -> None:
        """List the CLICK windows in the combobox and select the connected one.

        The connected window is always listed, under the project it shows: the
        list is read only now and then and leaves out a window whose title shows
        no project. *connected_title* is its title when the caller knows it.
        """
        click = self._app._click
        if click is not None:
            listed = next((i for i in self.click_instances if i.hwnd == click.hwnd), None)
            if listed is None or listed.filename != click.filename:
                title = connected_title or self._app.detector.get_window_title(click.hwnd) or ""
                entry = ClickInstance(click.pid, title, click.filename, click.hwnd)
                if listed is None:
                    self.click_instances = [*self.click_instances, entry]
                else:
                    self.click_instances = [
                        entry if instance is listed else instance
                        for instance in self.click_instances
                    ]
        self._app.instances_combobox["values"] = self._instance_labels()
        self._select_connected_instance()

    def refresh_click_instances(self):
        """List the running CLICK windows.

        Connects to the first one only when no window is connected and no data
        is loaded: connecting replaces the loaded data, so otherwise the user
        picks. The list leaves out windows whose title shows no project, so a
        connected window missing from it is closed only if its process is gone.
        """
        app = self._app
        try:
            click_instances = app.detector.get_click_instances()
        except Exception as e:
            print(f"Error refreshing Click instances: {e}")
            self.click_instances = []
            self._show_instances()
            app._update_status(f"⚠ Error: {e!s}", "error")
            app.start_button.state(["disabled"])
            return

        self.click_instances = click_instances
        click = app._click
        if (
            click is not None
            and all(instance.hwnd != click.hwnd for instance in click_instances)
            and not app.detector.check_window_exists(click.pid)
        ):
            self._handle_window_closed()
        self._show_instances()
        app._remove_stale_compare_copies({instance.hwnd for instance in self.click_instances})

        if not click_instances:
            app._update_status("⚠ No ClickPLC windows", "error")
            app.start_button.state(["disabled"])
            return
        app.start_button.state(["!disabled"])

        if app._click is None and app._data is None:
            first = click_instances[0]
            self.connect_to_instance(first.pid, first.title, first.filename, first.hwnd)

    # -- Connecting ----------------------------------------------------------

    def connect_to_instance(self, pid, title, filename, hwnd, *, user_picked: bool = False):
        """Connect to a specific Click.exe instance.

        A window the user picked turns monitoring on; an automatic connect
        leaves it as it is.
        """
        from .utils.mdb_shared import get_database_backend

        app = self._app
        if app._session is not None:
            app._session.cancel_load()

        # Close the current data first: its save prompts are the only step the
        # user can cancel, so nothing irreversible happens before them.
        if not app._close_data(prompt_save=True):
            self._select_connected_instance()
            return
        self.close_session()

        if user_picked:
            self.monitoring = True
            self._show_monitoring_button()

        # The session holds the window from now on, before its database loads
        self._open_connection_session(ClickConnection(pid, hwnd, filename))
        self._show_instances(title)

        if get_database_backend() == "none":
            self._connect_csv_fallback(filename, hwnd)
        else:
            self._load_instance_database(app._session)
        self._watch_connection()

    def _open_connection_session(
        self, click: ClickConnection, *, has_database: bool = False
    ) -> None:
        """Open the session for the connected window and pair its workspace.

        *has_database* when the loaded data is already this project's database
        (kept edits after a project change); otherwise the database load sets it.
        """
        from .connection_session import ConnectionSession

        app = self._app
        session = ConnectionSession(
            click,
            has_database=has_database,
            on_sync_status_changed=app._on_sync_status_changed,
            on_build_finished=app._on_build_finished,
        )
        session.load_workspace_pairing()
        app._session = session

    def close_session(self) -> None:
        """End the connection session: the one teardown of everything it owns."""
        session = self._app._session
        if session is not None:
            session.close()
            self._app._session = None

    def _load_instance_database(self, session: ConnectionSession) -> None:
        """Select a backend and load a private store before attaching it to Tk.

        The result counts only while *session* is open and nothing cancelled
        the load (``ConnectionSession.cancel_load``).
        """
        import queue
        import threading

        from .data.data_source import MdbDataSource

        app = self._app
        click = session.click
        token = session.begin_load()
        results = queue.Queue()
        app._update_status("Loading database...", "status")

        def load():
            try:
                data_source = MdbDataSource(click_pid=click.pid, click_hwnd=click.hwnd)
                store = AddressStore(data_source)
                store.load_initial_data()
                results.put((store, None))
            except Exception as exc:
                results.put((None, str(exc)))

        threading.Thread(target=load, daemon=True).start()

        def finish():
            if not session.loads(token):
                return
            try:
                store, error = results.get_nowait()
            except queue.Empty:
                app.root.after(100, finish)
                return
            if error is not None:
                app._show_main_window()
                app._update_status("Database connection failed", "error")
                self._odbc_warning_shown = True
                messagebox.showerror("Database Connection", error, parent=app.root)
                if session.loads(token):
                    self._connect_csv_fallback(click.filename, click.hwnd)
                return

            # The save prompt runs Tk's loop: the session may close meanwhile
            if not app._open_data(store, still_wanted=lambda: session.loads(token)):
                if session.loads(token):
                    app._update_status("Database load cancelled", "status")
                return
            session.has_database = True
            self.load_from_database()
            app._start_analysis_build()

        app.root.after(100, finish)

    def load_from_database(self):
        """Report the loaded database and watch its window."""
        app = self._app
        if app._click is None:
            app._update_status("⚠ Not connected", "error")
            return False

        # Check whether a database backend can be attempted
        if not app.nickname_manager.has_database_backend():
            app._update_status("No nicknames loaded - use File → Load Nicknames...", "status")
            if not self._odbc_warning_shown:
                app._show_odbc_warning()
                self._odbc_warning_shown = True
            return False

        if app._data is None:
            app._update_status("⚠ DB load failed", "error")
            return False

        app._update_status("✓ DB loaded", "connected")

        self._on_data_ready()
        return True

    def _connect_csv_fallback(self, filename, hwnd):
        """Offer CSV loading after a failed connection or an explicit CSV selection."""
        app = self._app
        app._show_main_window()
        fallback_csv = find_fallback_csv(hwnd)
        if fallback_csv:
            default_name = f"{filename.replace('.ckp', '')}_Address.csv"
            dialog = CsvFallbackDialog(app.root, fallback_csv, default_name)
            saved_path = dialog.show()
            if saved_path:
                self.load_csv(saved_path)
                return
        app._update_status("No nicknames loaded - use File → Load Nicknames...", "error")
        if not self._odbc_warning_shown:
            app._show_odbc_warning()
            self._odbc_warning_shown = True

    def load_csv(self, csv_path: str) -> bool:
        """Load nicknames from the CSV file at *csv_path*.

        Watches the connected window while it is still open; otherwise its
        session ends, as the data no longer follows it.
        """
        app = self._app
        if app._session is not None:
            app._session.cancel_load()
        try:
            from .data.data_source import CsvDataSource

            data_source = CsvDataSource(csv_path)
            store = AddressStore(data_source)
            store.load_initial_data()
            if not app._open_data(store):
                app._update_status("CSV load cancelled", "status")
                return False

            app._update_status("✓ CSV loaded", "connected")
            has_live_connection = app._click is not None and app.detector.check_window_exists(
                app._click.pid
            )
            if has_live_connection:
                self._on_data_ready()
            else:
                if app._session is not None:
                    self.close_session()
                    app.selected_instance_var.set("")
            return True
        except Exception as e:
            print(f"Error loading CSV: {e}")
            app._update_status("⚠ CSV load failed", "error")
            messagebox.showerror("CSV Load Failed", str(e), parent=app.root)
            return False

    def _on_data_ready(self) -> None:
        """Data for the connected window is loaded: watch the window, and while
        monitoring is on say so a second later (after the load's own status)."""
        self._watch_connection()
        if self.monitoring:
            self.cancel_monitoring_status()
            self._status_after_id = self._app.root.after(1000, self._update_status_monitoring)

    # -- Following the connected window ----------------------------------------

    def _handle_window_closed(self):
        """Handle when connected window is no longer available."""
        app = self._app
        app._update_status("⚠ Connected ClickPLC window closed", "error")
        self.cancel_monitoring_status()

        self.close_session()
        # Database data belongs to the closed project; CSV data stays usable.
        if app.using_database:
            app._close_data(prompt_save=False)

        app.selected_instance_var.set("")

        app.root.after(2000, self.refresh_click_instances)

    def _keeps_edits_for(self, old_filename: str, new_filename: str) -> bool:
        """Ask whether unsaved edits stay, for the project CLICK shows now.

        CLICK's Save As keeps the window's temp folder, its database and its
        DataView folder, and so does opening another project in the same
        window; ClickNick cannot tell the two apart, so the user says. The
        question covers address edits on database data, text in a cell that will
        not commit, and Dataview edits (on CSV data too: the Dataview Editor
        shows the window's DataView folder). CSV address edits belong to the CSV
        file and are not asked about. Nothing is saved here. False when there is
        nothing unsaved.
        """
        data = self._app._data
        if data is None:
            return False
        unsaved = []
        if data.store.is_database:
            # A cell that will not commit (CLICK has the focus) still holds an edit
            committed = data.commit_open_cell_editors()
            if not committed or data.store.has_unsaved_changes():
                unsaved.append("address changes")
        dataview = data.dataview_window
        if dataview is not None:
            committed = dataview.commit_open_cell_editor()
            if not committed or dataview.has_unsaved_changes():
                unsaved.append("Dataview changes")
        if not unsaved:
            return False
        saves = "Sync and Save then write them" if data.store.is_database else "Save writes them"
        return messagebox.askyesno(
            "Project Changed",
            f"The CLICK window now shows {new_filename}. You have unsaved "
            f"{' and '.join(unsaved)} made in {old_filename}.\n\n"
            f"Keep them as unsaved changes for {new_filename}? Choose Yes after a Save As in "
            f"CLICK: {saves} to {new_filename}.\n\n"
            "No discards them and saves nothing.",
            icon=messagebox.WARNING,
            parent=self._app.root,
        )

    def _reopen_dataview_editor(self, *, kept: bool) -> None:
        """After a project change, show the window's DataView folder as it is now.

        The window keeps its ``CLICK (hwnd)`` folder. When the user kept the
        edits (*kept*) the editor stays as it is, with its tabs and its Modbus
        connection, and lists the folder again. Otherwise it shows the files of
        the project CLICK had open: it is closed without saving and opened again
        on the window's DataView folder.
        """
        data = self._app._data
        dataview = data.dataview_window if data is not None else None
        if dataview is None:
            return
        if kept:
            dataview.refresh_file_list()
            return
        dataview.close_without_prompt()
        self._app._open_dataview_editor()

    def _handle_project_change(self, current_title: str, new_filename: str) -> None:
        """The connected CLICK window shows another project: follow it.

        Unsaved address edits on database data, and Dataview edits, are kept
        for the new project or discarded, as the user says (``_keeps_edits_for``).
        Kept, the data and its windows stay open, and the store's file monitor
        reads the base from the database the window now holds. Otherwise
        database data closes with nothing saved, and the new project's database
        is loaded. CSV data stays loaded. A Dataview Editor that stays open
        lists its folder again when the edits were kept, and is otherwise opened
        again on the window's DataView folder (``_reopen_dataview_editor``).
        Monitoring stays as it was.
        """
        app = self._app
        session = app._session
        if session is None:
            return
        click = session.click
        keep = self._keeps_edits_for(click.filename, new_filename)
        closes_data = app.using_database and not keep
        closing = []
        if closes_data and app._data.has_open_windows:
            closing.append("Editor windows")
        if session.simulator is not None:
            closing.append("the Simulator" if closing else "The Simulator")
        if closing:
            messagebox.showinfo(
                "Project Changed",
                f"The Click project was changed. {' and '.join(closing)} will now close.",
            )

        self.close_session()
        if closes_data:
            app._close_data(prompt_save=False)

        kept_database = keep and app.using_database
        self._open_connection_session(
            replace(click, filename=new_filename), has_database=kept_database
        )
        self._show_instances(current_title)
        self._reopen_dataview_editor(kept=keep)

        if kept_database:
            app._update_status(f"Kept unsaved changes for {new_filename}", "connected")
            self._on_data_ready()
            app._start_analysis_build()
        elif app._data is None and app.nickname_manager.has_database_backend():
            # Same off-thread load as connecting; a result for a project that
            # changed again is dropped with its session.
            self._load_instance_database(app._session)
        elif self.monitoring:
            self._update_status_monitoring()

    # -- The watch and the popup -----------------------------------------------

    def _handle_popup_window(self, window_id, window_class, edit_control):
        """Handle the detected popup window by showing or updating the nickname popup."""
        app = self._app
        session = app._session
        if session is None:
            return
        try:
            # Create overlay if it doesn't exist
            if not session.overlay:
                session.overlay = Overlay(
                    app.root,
                    app.nickname_manager,
                )
            # Update target window info
            session.overlay.set_target_window(window_id, window_class, edit_control)

            # Get allowed types for this window/control
            field_info = app.detector.update_window_info(window_class, edit_control)

            # Show the overlay with filtered nicknames
            session.overlay.show_combobox(field_info.allowed_address_types)

        except Exception as e:
            print(f"Error showing overlay: {e}")

    def _handle_popup_detection(self, session: ConnectionSession) -> None:
        """Check for Click.exe child popups and show/hide overlay accordingly."""
        detector = self._app.detector
        child_info = detector.detect_child_window(session.click.pid)
        if child_info:
            if not detector.field_has_text(child_info.edit_control, child_info.window_id):
                self._handle_popup_window(
                    child_info.window_id, child_info.window_class, child_info.edit_control
                )
        elif session.overlay:
            session.overlay.withdraw()

    def _monitor_task(self):
        """Every 100 ms while a CLICK window is connected (the session's watch):
        notice it closing or changing project and, while monitoring is on, its
        instruction popups.

        Stop turns off only the popups; the watch ends when the session does.
        Popups need loaded data.
        """
        app = self._app
        session = app._session
        if session is None:
            return
        click = session.click
        if not app.detector.check_window_exists(click.pid):
            self._handle_window_closed()
            return

        current_title = app.detector.get_window_title(click.hwnd)
        new_filename = ClickWindowDetector.parse_click_filename(current_title)
        if new_filename and new_filename != click.filename:
            try:
                self._handle_project_change(current_title, new_filename)
            finally:
                # The new project's session watches from here, starting now, even
                # when following the project failed part way (the old session's
                # watch ended when it closed)
                self._watch_connection()
            return

        if self.monitoring and app._data is not None:
            if not (session.overlay and session.overlay.is_active()):
                self._handle_popup_detection(session)
        else:
            session.hide_overlay()

    def _watch_connection(self) -> None:
        """Start the connected session's watch (_monitor_task) unless it runs already."""
        session = self._app._session
        if session is not None:
            session.watch(self._app.root, self._monitor_task)

    # -- Monitoring ------------------------------------------------------------

    def cancel_monitoring_status(self) -> None:
        """Drop the Monitoring status shown a second after a load, if it is still due."""
        if self._status_after_id is not None:
            self._app.root.after_cancel(self._status_after_id)
            self._status_after_id = None

    def _show_monitoring_button(self) -> None:
        self._app.start_button.configure(text="⏹ Stop" if self.monitoring else "▶ Start")

    def _update_status_monitoring(self):
        """Update Status and Button to reflect Monitoring"""
        self.cancel_monitoring_status()
        click = self._app._click
        if not self.monitoring or click is None:
            return
        self._app._update_status(f"⚡ Monitoring {click.filename}", "connected")
        self._show_monitoring_button()

    def _start_monitoring_internal(self) -> bool:
        """Internal method to start monitoring without status updates.
        Returns True if successful, False otherwise."""
        # Validate connection to Click instance
        if self._app._click is None:
            self._app._update_status("⚠ Not connected to ClickPLC window", "error")
            return False

        try:
            self.monitoring = True
            self._watch_connection()
            return True
        except Exception as e:
            self._app._update_status(f"⚠ Monitoring failed: {str(e)}", "error")
            return False

    def button_start_monitoring(self):
        """Start monitoring with immediate status update."""
        if self._start_monitoring_internal():
            self._update_status_monitoring()

    def stop_monitoring(self):
        """Turn off popup detection; the connection watch keeps running."""
        self.monitoring = False
        self.cancel_monitoring_status()
        if self._app._session is not None:
            self._app._session.hide_overlay()
        self._app._update_status("⏹ Stopped", "status")
        self._show_monitoring_button()

    def toggle_monitoring(self):
        """Start or stop monitoring."""
        if self.monitoring:
            self.stop_monitoring()
        else:
            self.button_start_monitoring()
