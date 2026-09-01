"""LiveServer: out-of-process command attachment embedded in the GUI.

A background daemon thread accepts localhost connections. Each command is
pushed onto a thread-safe queue and executed on the Tk main thread by a
periodic ``root.after`` drain loop, because tkinter is single-threaded and
the edit triggers observer refreshes that touch widgets.

The socket thread blocks (only itself) on a per-request ``threading.Event``
until the Tk thread has produced a result, then ships it back.

The TCP listener lives for the whole app lifetime (one port), but the *port
file* that advertises it follows the connection: a second, slower ``after``
loop republishes it into the current session directory (the connected CLICK
instance's folder, else the ClickNick fallback) whenever that changes.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from multiprocessing.connection import Listener
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .dispatch import DispatchContext, dispatch
from .session import LABEL_FILENAME, PORT_FILENAME, WORKSPACE_FILENAME

if TYPE_CHECKING:
    import tkinter as tk

    from ..data.address_store import AddressStore
    from ..services.analysis_service import AnalysisService

# How often the Tk thread drains queued commands (ms). Low for CLI snappiness.
_DRAIN_INTERVAL_MS = 50
# How often the Tk thread re-checks where to advertise the port file (ms).
_ADVERTISE_INTERVAL_MS = 1000
# Max time the socket thread waits for the Tk thread to run a command (s).
_REQUEST_TIMEOUT_S = 60.0


class _Request:
    """One queued command awaiting execution on the Tk thread."""

    __slots__ = ("command", "done", "result")

    def __init__(self, command: str) -> None:
        self.command = command
        self.done = threading.Event()
        self.result: str = "ERROR: timed out waiting for the app"


class LiveServer:
    """TCP command server embedded in the running ClickNick app.

    Args:
        root: The Tk root (used for ``after`` scheduling on the main thread).
        get_store: Callable returning the *current* ``AddressStore`` (or None).
            A callable, not a snapshot, because the store is recreated on
            reconnect/project-switch and is None when nothing is loaded.
        get_session_dir: Callable returning the directory to advertise the port
            file in (or None to advertise nowhere). Re-checked periodically so
            the port file follows the active CLICK connection.
    """

    def __init__(
        self,
        root: tk.Tk,
        get_store: Callable[[], AddressStore | None],
        get_session_dir: Callable[[], Path | None],
        get_session_label: Callable[[], str | None] | None = None,
        get_analysis: Callable[[], AnalysisService | None] | None = None,
        get_workspace_dir: Callable[[], Path | None] | None = None,
        get_click_hwnd: Callable[[], int | None] | None = None,
        get_mdb_path: Callable[[], Path | None] | None = None,
        get_synced_pending: Callable[[], int] | None = None,
        get_staged_rungs: Callable[[], int] | None = None,
        record_staged_rungs: Callable[[int], None] | None = None,
        get_pyrung_live_available: Callable[[], bool] | None = None,
        open_editor: Callable[[str], None] | None = None,
    ) -> None:
        self._root = root
        self._get_store = get_store
        self._get_session_dir = get_session_dir
        self._get_session_label = get_session_label
        self._get_analysis = get_analysis
        self._get_workspace_dir = get_workspace_dir
        self._get_click_hwnd = get_click_hwnd
        self._get_mdb_path = get_mdb_path
        self._get_synced_pending = get_synced_pending
        self._get_staged_rungs = get_staged_rungs
        self._record_staged_rungs = record_staged_rungs
        self._get_pyrung_live_available = get_pyrung_live_available
        self._open_editor = open_editor
        self._listener: Listener | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._queue: queue.Queue[_Request] = queue.Queue()
        self._port: int | None = None
        self._drain_after_id: str | None = None
        self._advertise_after_id: str | None = None
        self._published_dir: Path | None = None

    @property
    def port(self) -> int | None:
        return self._port

    def _handle(self, conn: Any) -> None:
        raw = conn.recv_bytes()
        command = raw.decode("utf-8").strip()
        if not command:
            conn.send_bytes(b"ERROR: empty command")
            return

        request = _Request(command)
        self._queue.put(request)
        request.done.wait(timeout=_REQUEST_TIMEOUT_S)
        conn.send_bytes(request.result.encode("utf-8"))

    # -- socket thread ------------------------------------------------------

    def _accept_loop(self) -> None:
        listener = self._listener
        assert listener is not None
        while not self._stop.is_set():
            try:
                conn = listener.accept()
            except OSError:
                break
            try:
                self._handle(conn)
            except Exception:
                pass
            finally:
                conn.close()

    # -- Tk main thread -----------------------------------------------------

    def _build_context(self) -> DispatchContext:
        """Build a fresh dispatch context from current getter values."""
        analysis = self._get_analysis() if self._get_analysis else None
        mdb_path = self._get_mdb_path() if self._get_mdb_path else None
        project_saved = None if mdb_path is None else any(mdb_path.parent.glob("Scr*.tmp"))
        resolve_tag = None
        if analysis is not None and analysis.is_available:
            resolve_tag = analysis.tag_to_addr_key.get

        show_preview = None
        if self._root is not None:
            get_hwnd = self._get_click_hwnd
            get_mdb = self._get_mdb_path

            def _open_preview(
                file_stem: str,
                selection: str | None,
                diff_text: str,
                rung_nums: list[int] | None,
                pending_dir: Path,
                csv_stem: str | None = None,
            ) -> None:
                from ..views.rung_preview_window import RungPreviewWindow

                RungPreviewWindow(
                    self._root,
                    diff_text,
                    file_stem=file_stem,
                    selection=selection,
                    rung_nums=rung_nums,
                    pending_dir=pending_dir,
                    get_click_hwnd=get_hwnd,
                    get_mdb_path=get_mdb,
                    csv_stem=csv_stem,
                )

            show_preview = _open_preview

        show_address_editor = self._open_editor

        show_save_prompt = None
        if self._root is not None:

            def _prompt_save(title: str, message: str) -> None:
                from tkinter import messagebox

                messagebox.showinfo(title, message, parent=self._root)

            show_save_prompt = _prompt_save

        synced_pending = self._get_synced_pending() if self._get_synced_pending else 0
        staged_rungs = self._get_staged_rungs() if self._get_staged_rungs else 0
        pyrung_live_available = (
            self._get_pyrung_live_available() if self._get_pyrung_live_available else False
        )

        return DispatchContext(
            store=self._get_store(),
            resolve_tag=resolve_tag,
            analysis=analysis,
            show_preview=show_preview,
            show_address_editor=show_address_editor,
            show_save_prompt=show_save_prompt,
            record_staged_rungs=self._record_staged_rungs,
            synced_pending=synced_pending,
            staged_rungs=staged_rungs,
            project_saved=project_saved,
            pyrung_live_available=pyrung_live_available,
        )

    def dispatch_now(self, command: str) -> str:
        """Run a command immediately from the Tk thread.

        Main-window actions use this to share the exact reviewed workflows
        exposed by the live CLI without making a socket round trip.
        """
        return dispatch(self._build_context(), command)

    def _drain(self) -> None:
        """Execute queued commands on the Tk thread, then reschedule."""
        try:
            while True:
                request = self._queue.get_nowait()
                try:
                    ctx = self._build_context()
                    request.result = dispatch(ctx, request.command)
                except Exception as exc:  # noqa: BLE001 - reported back to client
                    request.result = f"ERROR: {exc}"
                finally:
                    request.done.set()
        except queue.Empty:
            pass
        if not self._stop.is_set():
            self._drain_after_id = self._root.after(_DRAIN_INTERVAL_MS, self._drain)

    def _unpublish(self) -> None:
        """Remove the port and label files from the directory they were last published to."""
        if self._published_dir is not None:
            for fname in (PORT_FILENAME, LABEL_FILENAME, WORKSPACE_FILENAME):
                try:
                    (self._published_dir / fname).unlink(missing_ok=True)
                except OSError:
                    pass
            self._published_dir = None

    def _refresh_workspace_metadata(self) -> None:
        """Advertise the active path without coupling it to port discovery."""
        directory = self._published_dir
        if directory is None:
            return
        workspace_file = directory / WORKSPACE_FILENAME
        try:
            workspace = self._get_workspace_dir() if self._get_workspace_dir else None
            if workspace is None:
                workspace_file.unlink(missing_ok=True)
            else:
                workspace_file.write_text(str(workspace), encoding="utf-8")
        except OSError:
            pass

    def _refresh_advertisement(self) -> None:
        """Republish the port file if the target session dir changed."""
        try:
            target = self._get_session_dir()
        except Exception:
            target = None
        if target != self._published_dir:
            self._unpublish()
            if target is not None and self._port is not None:
                try:
                    target.mkdir(parents=True, exist_ok=True)
                    (target / PORT_FILENAME).write_text(str(self._port), encoding="utf-8")
                    label = self._get_session_label() if self._get_session_label else None
                    if label:
                        (target / LABEL_FILENAME).write_text(label, encoding="utf-8")
                    else:
                        (target / LABEL_FILENAME).unlink(missing_ok=True)
                    self._published_dir = target
                except OSError:
                    self._published_dir = None
        self._refresh_workspace_metadata()
        if not self._stop.is_set():
            self._advertise_after_id = self._root.after(
                _ADVERTISE_INTERVAL_MS, self._refresh_advertisement
            )

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Open the socket and begin serving + advertising.

        Must be called from the Tk thread (it schedules the ``after`` loops).
        """
        if self._listener is not None:
            return
        self._listener = Listener(("localhost", 0), family="AF_INET")
        self._port = int(self._listener.address[1])

        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            daemon=True,
            name="clicknick-live",
        )
        self._accept_thread.start()
        self._drain_after_id = self._root.after(_DRAIN_INTERVAL_MS, self._drain)
        self._refresh_advertisement()  # publish immediately, then reschedule

    def stop(self) -> None:
        """Stop serving, remove the port file, and close the socket."""
        self._stop.set()
        for after_id in (self._drain_after_id, self._advertise_after_id):
            if after_id is not None:
                try:
                    self._root.after_cancel(after_id)
                except Exception:
                    pass
        self._drain_after_id = None
        self._advertise_after_id = None
        self._unpublish()
        if self._listener is not None:
            self._listener.close()  # unblocks accept() with OSError
            self._listener = None
