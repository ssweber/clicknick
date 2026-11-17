"""Connect to CLICK windows and follow the connected one.

``ConnectionController`` lists the CLICK windows and connects to one. Connecting opens the
window's ``ConnectionSession`` and loads its database, or offers the CSV fallback. The
controller also follows a project change, notices the window closing, shows the
autocomplete popup while monitoring is on, and has the window redraw its nicknames
(``redraw_nicknames``).

The controller changes the session and the data only through the app. The session lives in
``ClickNickApp._session``. The data lives in ``ClickNickApp._data``, and the controller
changes it through ``_open_data`` and ``_close_data``. The controller keeps only this state
of its own:

- the CLICK windows that the combobox lists (``click_instances``);
- whether the user turned autocomplete popups on (``monitoring``);
- the Monitoring status line that is due a second after a load (``_status_after_id``);
- whether the ODBC warning has shown;
- whether a nickname redraw is running, and the request made while it runs
  (``_redraw_pending``).
"""

from __future__ import annotations

import logging
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

    from .config import AppSettings
    from .connection_session import ConnectionSession
    from .data.nickname_manager import NicknameManager
    from .data_session import DataSession
    from .services.click_redraw import RedrawResult
    from .views.redraw_splash import RedrawSplash

logger = logging.getLogger(__name__)

# The Tools menu command that redraws CLICK's nicknames
REDRAW_COMMAND = "Redraw Nicknames in CLICK"
# The Tools menu setting that redraws them after each Sync
REDRAW_ON_SYNC = "Redraw Ladder on Sync"


class ConnectionHost(Protocol):
    """The part of the app (``ClickNickApp``) that ConnectionController uses."""

    root: tk.Tk
    settings: AppSettings
    # The connected session and the loaded data live only here. Assigning either one
    # refreshes the main window.
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
        # Whether autocomplete popups are on. Only the user's Start/Stop, or a window the
        # user picks, changes it. The connection watch (_monitor_task) runs whenever a
        # CLICK window is connected, whatever this says.
        self.monitoring = True
        self._status_after_id = None
        self._odbc_warning_shown = False
        # Whether a nickname redraw is running (redraw_nicknames). A redraw requested
        # meanwhile is kept as (CLICK window, after_sync) and runs when the running one ends.
        self._redraw_running = False
        self._redraw_pending: tuple[int, bool] | None = None

    # -- The window list -----------------------------------------------------

    def _instance_labels(self) -> list[str]:
        """Return the combobox label for each CLICK window.

        The label is the filename, plus the PID if two windows show the same filename.
        """
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
        """Select the connected CLICK window in the combobox, or clear it if none is connected."""
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

        The connected window is always listed, under the project it shows. The list is read
        only now and then, and it leaves out a window whose title shows no project.
        *connected_title* is the window's title if the caller knows it.
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

        Connect to the first one only if no window is connected and no data is loaded.
        Connecting replaces the loaded data, so in other cases the user picks. The list
        leaves out windows whose title shows no project. So a connected window that is
        missing from the list is closed only if its process is gone.
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

        A window that the user picked turns monitoring on. An automatic connect leaves
        monitoring as it is.
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

        *has_database* is True when the loaded data is already this project's database
        (kept edits after a project change). Otherwise the database load sets it.
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
        """End the connection session and tear down everything it owns."""
        session = self._app._session
        if session is not None:
            session.close()
            self._app._session = None

    def _load_instance_database(self, session: ConnectionSession) -> None:
        """Load the window's database into a private store on a thread, then attach it to Tk.

        The result is used only if *session* is still open and nothing called
        ``ConnectionSession.cancel_load``.
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

        If the connected window is still open, watch it. Otherwise end its session, because
        the data no longer follows it.
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
        """Handle data that has loaded for the connected window.

        Watch the window. If monitoring is on, show the Monitoring status a second later,
        after the load's own status.
        """
        self._watch_connection()
        if self.monitoring:
            self.cancel_monitoring_status()
            self._status_after_id = self._app.root.after(1000, self._update_status_monitoring)

    # -- Following the connected window ----------------------------------------

    def _handle_window_closed(self):
        """Clean up after the connected window closed, and refresh the window list in 2 seconds."""
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
        """Ask whether unsaved edits stay with the project CLICK shows now.

        CLICK's Save As keeps the window's temp folder, its database and its DataView
        folder. Opening another project in the same window does the same. ClickNick cannot
        tell the two apart, so the user answers. The question covers address edits on
        database data, text in a cell that will not commit, and Dataview edits. Dataview
        edits count on CSV data too, because the Dataview Editor shows the window's
        DataView folder. CSV address edits belong to the CSV file, so the question does
        not cover them. Nothing is saved here. Return False if nothing is unsaved.
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
            f"CLICK. {saves} to {new_filename}.\n\n"
            "No discards them and saves nothing.",
            icon=messagebox.WARNING,
            parent=self._app.root,
        )

    def _reopen_dataview_editor(self, *, kept: bool) -> None:
        """Show the window's DataView folder as it is now, after a project change.

        The window keeps its ``CLICK (hwnd)`` folder. If the user kept the edits (*kept*),
        the editor stays as it is, with its tabs and its Modbus connection, and lists the
        folder again. Otherwise the editor is closed without saving and opened again on the
        window's DataView folder, so it shows the files of the project CLICK had open.
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
        """Follow the connected CLICK window to another project.

        The user decides whether unsaved address edits on database data, and Dataview edits,
        are kept for the new project or discarded (``_keeps_edits_for``). If they are kept,
        the data and its windows stay open, and the store's file monitor reads the base from
        the database that the window now holds. Otherwise database data closes with nothing
        saved, and the new project's database is loaded. CSV data stays loaded. A Dataview
        Editor that stays open lists its folder again if the edits were kept. Otherwise it
        is opened again on the window's DataView folder (``_reopen_dataview_editor``).
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
            # This is the same off-thread load as connecting. If the project changes again,
            # the result is dropped with its session.
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
            field_info = app.detector.update_window_info(window_class, edit_control, window_id)

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
        """Run every 100 ms while a CLICK window is connected (the session's watch).

        Notice the window closing or changing project. While monitoring is on, also notice
        its instruction popups.

        Stop turns off only the popups. The watch ends when the session does. Popups need
        loaded data.
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
                # Start the watch of the new project's session now, even if following the
                # project failed part way. The old session's watch ended when it closed.
                self._watch_connection()
            return

        if self.monitoring and app._data is not None:
            if not (session.overlay and session.overlay.is_active()):
                self._handle_popup_detection(session)
        else:
            session.hide_overlay()

    def _watch_connection(self) -> None:
        """Start the connected session's watch (_monitor_task) unless it is already running."""
        session = self._app._session
        if session is not None:
            session.watch(self._app.root, self._monitor_task)

    # -- Redrawing CLICK's nicknames -------------------------------------------

    def after_sync(self) -> None:
        """Make CLICK redraw the nicknames that a Sync just wrote into its database.

        If the user turned Tools > Redraw Ladder on Sync off, redraw nothing. The status
        line then says how to show the new names.
        """
        if self._app.settings.redraw_on_sync:
            self.redraw_nicknames(after_sync=True)
            return
        self._app._update_status(
            f"✓ Synced into CLICK's database. Use Tools > {REDRAW_COMMAND} "
            "to show the new names in CLICK's ladder",
            "connected",
        )

    def redraw_nicknames(self, *, after_sync: bool) -> None:
        """Make the connected CLICK window redraw its nicknames from SC_.mdb.

        Run ``services.click_redraw.redraw_nicknames`` on a thread of its own and show the
        result in the status line. While the redraw runs, a notice (``RedrawSplash``) shows
        over CLICK's window. The notice goes before the status line shows the result. So it
        never hides a dialog that the redraw leaves to the user.

        Pass *after_sync* when a Sync has just written nicknames. If the redraw is skipped
        or fails, the status line then says that the nicknames are in CLICK's database and
        how to redraw them.

        If you call this while a redraw runs, the request runs after that redraw ends. That
        redraw may have read SC_.mdb before the Sync wrote it. Several requests made
        meanwhile run once.

        If another CLICK window, or none, is connected when a redraw ends, the status line
        shows nothing, and the waiting request does not run. A project change opens a new
        session on the same window. The redraw then still shows its result, and the waiting
        request still runs.
        """
        session = self._app._session
        if session is None:
            self._app._update_status("⚠ Connect to a CLICK window first", "error")
            return
        if self._redraw_running:
            hwnd = session.click.hwnd
            pending = self._redraw_pending
            again = after_sync or (pending is not None and pending[0] == hwnd and pending[1])
            self._redraw_pending = (hwnd, again)
            return
        self._start_redraw(session, after_sync)

    def _start_redraw(self, session: ConnectionSession, after_sync: bool) -> None:
        import os
        import queue

        from .services.click_redraw import RedrawOutcome, RedrawResult, redraw_nicknames

        self._redraw_running = True
        results: queue.Queue[RedrawResult] = queue.Queue(maxsize=1)
        click = session.click
        own_pid = os.getpid()

        def work() -> None:
            try:
                from .utils.win32_desktop import Win32ClickDesktop

                result = redraw_nicknames(
                    Win32ClickDesktop(), int(click.pid), click.hwnd, own_pid=own_pid
                )
            except Exception as exc:
                result = RedrawResult(RedrawOutcome.FAILED, str(exc) or type(exc).__name__)
            results.put(result)

        def finish() -> None:
            try:
                result = results.get_nowait()
            except queue.Empty:
                self._app.root.after(100, finish)
                return
            self._close_splash(splash)
            self._redraw_running = False
            current = self._app._session
            if current is not None and current.click.hwnd == click.hwnd:
                self._report_redraw(result, after_sync)
            pending, self._redraw_pending = self._redraw_pending, None
            if pending is not None and current is not None and current.click.hwnd == pending[0]:
                self._start_redraw(current, pending[1])

        splash = self._show_splash(click.hwnd)
        try:
            self._run_off_tk(work)
        except BaseException:
            self._close_splash(splash)
            self._redraw_running = False
            raise
        self._app.root.after(100, finish)

    def _show_splash(self, click_hwnd: int) -> RedrawSplash | None:
        """Show the notice over the CLICK window *click_hwnd*, or return None if it fails.

        The redraw runs without the notice when it cannot be shown.
        """
        from .views.redraw_splash import RedrawSplash

        try:
            return RedrawSplash(self._app.root, click_hwnd)
        except Exception:
            logger.exception("Could not show the redraw notice")
            return None

    @staticmethod
    def _close_splash(splash: RedrawSplash | None) -> None:
        if splash is not None:
            splash.close()

    @staticmethod
    def _run_off_tk(work: Callable[[], None]) -> None:
        """Run *work* on a thread of its own.

        The thread is not a daemon, so a redraw started as ClickNick closes (the save
        prompt's Sync) runs to its end. Its waits are bounded. That takes about a minute at
        worst, and a second or two when CLICK answers.
        """
        import threading

        threading.Thread(target=work, name="clicknick-redraw").start()

    def _report_redraw(self, result: RedrawResult, after_sync: bool) -> None:
        from .services.click_redraw import RedrawOutcome

        app = self._app
        if result.outcome is RedrawOutcome.REFRESHED:
            app._update_status("✓ CLICK shows the nicknames from its database", "connected")
            return
        busy = result.outcome is RedrawOutcome.BUSY
        if after_sync:
            what = "CLICK was busy" if busy else "CLICK did not redraw them"
            message = (
                f"⚠ Synced into CLICK's database, but {what} ({result.detail}). "
                f"Use Tools > {REDRAW_COMMAND} to show them"
            )
        elif busy:
            message = f"⚠ CLICK is busy ({result.detail}). Close its dialog and try again"
        else:
            message = f"⚠ CLICK did not redraw its nicknames ({result.detail})"
        app._update_status(message, "error")

    # -- Monitoring ------------------------------------------------------------

    def cancel_monitoring_status(self) -> None:
        """Cancel the Monitoring status due a second after a load, if it is still pending."""
        if self._status_after_id is not None:
            self._app.root.after_cancel(self._status_after_id)
            self._status_after_id = None

    def _show_monitoring_button(self) -> None:
        self._app.start_button.configure(text="⏹ Stop" if self.monitoring else "▶ Start")

    def _update_status_monitoring(self):
        """Show the Monitoring status and update the button when monitoring is on."""
        self.cancel_monitoring_status()
        click = self._app._click
        if not self.monitoring or click is None:
            return
        self._app._update_status(f"⚡ Monitoring {click.filename}", "connected")
        self._show_monitoring_button()

    def _start_monitoring_internal(self) -> bool:
        """Start monitoring but do not show the Monitoring status.

        Return True if monitoring started, False otherwise.
        """
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
        """Turn off popup detection. The connection watch keeps running."""
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
