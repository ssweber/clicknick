"""Interactive pyrung simulation console.

Singleton window accessible from Tools > Console. Auto-launches the pyrung
DAP subprocess on open, pipes user commands to the pyrung LiveServer via
``pyrung.dap.live.send_command()``, and terminates the DAP on close.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING, Any

from ..services.console_completer import ConsoleCompleter
from ..widgets.console_input import ConsoleInput
from ..widgets.tooltip import bind_tooltip

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..data.address_store import AddressStore
    from ..services.analysis_service import AnalysisService

_PLC_DATA_WATCH_MS = 2000
_ANALYSIS_POLL_MS = 500
_COPY_FLASH_MS = 1200
#: Give a large program room to convert, but never poll forever.
_ANALYSIS_TIMEOUT_MS = 120_000
# Plain text, not a clipboard emoji: the emoji renders in colour from a
# different font and sits oddly among ttk's monochrome controls.
_COPY_LABEL = "Copy"
_COPIED_LABEL = "Copied"


class ConsoleWindow(tk.Toplevel):
    """Interactive pyrung simulation console."""

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _append_output(self, text: str, tag: str | None = None) -> None:
        self._output.configure(state="normal")
        if tag:
            self._output.insert(tk.END, text, tag)
        else:
            self._output.insert(tk.END, text)
        self._output.configure(state="disabled")
        self._output.see(tk.END)

    def _restore_copy_button(self) -> None:
        self._copy_flash_after_id = None
        if not self._destroyed:
            self._copy_btn.configure(text=_COPY_LABEL)

    def _flash_copy_button(self) -> None:
        if self._copy_flash_after_id is not None:
            try:
                self.after_cancel(self._copy_flash_after_id)
            except Exception:
                pass
        self._copy_btn.configure(text=_COPIED_LABEL)
        self._copy_flash_after_id = self.after(_COPY_FLASH_MS, self._restore_copy_button)

    def _copy_output(self) -> None:
        """Copy the output selection, or the whole transcript when nothing is selected."""
        if self._output.tag_ranges(tk.SEL):
            text = self._output.get(tk.SEL_FIRST, tk.SEL_LAST)
        else:
            text = self._output.get("1.0", tk.END)
        text = text.rstrip("\n")
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._flash_copy_button()

    # ------------------------------------------------------------------
    # DAP lifecycle
    # ------------------------------------------------------------------

    def _show_retry(self) -> None:
        if not self._retry_btn.winfo_ismapped():
            self._retry_btn.pack(side=tk.LEFT, padx=(4, 0))

    def _report_startup_failure(self, reason: str, detail: str | None = None) -> None:
        """Explain why the console cannot start, and offer a retry."""
        self._append_output(f"Cannot start simulation: {reason}\n", "error")
        if detail:
            self._append_output(detail.rstrip() + "\n", "progress")
        self._status_var.set("Not available")
        self._show_retry()

    def _wait_for_analysis(self) -> None:
        """Show progress while the conversion runs, and schedule the next poll.

        Every waiting path routes through here, so the timeout is enforced in
        one place no matter which check decided to wait.
        """
        if self._analysis_waited_ms >= _ANALYSIS_TIMEOUT_MS:
            self._report_startup_failure(
                f"timed out after {_ANALYSIS_TIMEOUT_MS // 1000}s waiting for "
                "program analysis to finish."
            )
            return
        seconds = self._analysis_waited_ms // 1000
        elapsed = f" ({seconds}s)" if seconds else ""
        self._status_var.set(f"Building program analysis...{elapsed}")
        self._analysis_waited_ms += _ANALYSIS_POLL_MS
        self._analysis_after_id = self.after(_ANALYSIS_POLL_MS, self._poll_analysis)

    def _on_dap_failed(self, exc: Exception) -> None:
        from ..services.analysis_service import AnalysisStatus

        analysis = self._get_analysis()
        if analysis is not None and (
            analysis.status is AnalysisStatus.BUILDING
            or analysis.generation != self._launch_generation
        ):
            # The launch runs on a worker thread against files on disk, so a
            # rebuild can rewrite the project underneath it -- yielding partial
            # imports ("No module named 'subroutines'"), a missing run.py, or
            # anything else half-written. The generation check catches the case
            # where that rebuild also *finished* before we got here, so the
            # status alone no longer looks suspicious. Wait and relaunch rather
            # than reporting the rubble as a real failure.
            self._wait_for_analysis()
            return
        self._append_output(f"Simulation backend failed to start: {exc}\n", "error")
        self._status_var.set("Error")
        self._show_retry()

    def _schedule_ui(self, callback: Callable[[], None]) -> None:
        if self._destroyed:
            return
        try:
            self.after(0, callback)
        except tk.TclError:
            pass

    def _on_dap_state_bg(self, state: Any, error: Exception | None) -> None:
        label = state.value
        if error:
            label = f"{label}: {error}"
        self._schedule_ui(lambda: self._status_var.set(label))

    def _on_dap_scan_bg(self, scan_id: int | None) -> None:
        self._schedule_ui(lambda: self._status_var.set(f"Running | Scan: {scan_id}"))

    def _hide_retry(self) -> None:
        if self._retry_btn.winfo_ismapped():
            self._retry_btn.pack_forget()

    def _start_dap(self) -> None:
        from ..services.analysis_service import AnalysisStatus

        analysis = self._get_analysis()
        if analysis is None:
            self._report_startup_failure(
                "program analysis has not started. Connect to a Click project, "
                "then save it in Click Software."
            )
            return

        # A build rewrites the generated project in place, so while one is
        # running the folder on disk is rubble regardless of what the previous
        # result still advertises. Wait it out before touching any of it.
        if analysis.status is AnalysisStatus.BUILDING:
            self._wait_for_analysis()
            return

        # A usable result wins even if a later rebuild failed -- stale analysis
        # beats no console.
        if not analysis.is_available:
            if analysis.status is AnalysisStatus.FAILED:
                self._report_startup_failure(
                    analysis.error or "converting the program to pyrung failed.",
                    analysis.error_detail,
                )
                return
            self._wait_for_analysis()
            return

        self._hide_retry()
        project_dir = analysis.project_dir
        if project_dir is None:
            self._report_startup_failure(
                "no pyrung project folder was generated. "
                "Save the project in Click Software, then retry."
            )
            return

        # A rebuild empties this folder before regenerating it, so while one is
        # running the directory can exist with run.py not yet written.
        if not (project_dir / "run.py").is_file():
            self._report_startup_failure(
                f"the generated project at {project_dir} has no run.py. "
                "Save the project in Click Software, then retry."
            )
            return

        self._status_var.set("Starting...")
        snapshot_path = self._plc_data_path
        # Remembered so a failure can tell "the project was rewritten under the
        # launch" from "this project genuinely does not run".
        self._launch_generation = analysis.generation

        def _launch() -> None:
            from ..services.dap_service import DapService

            try:
                dap = DapService(
                    on_state=self._on_dap_state_bg,
                    on_scan=self._on_dap_scan_bg,
                )
                dap.launch(
                    project_dir,  # type: ignore[arg-type]
                    snapshot_path=snapshot_path,
                    session_name=self._session_name,
                )
                self._schedule_ui(lambda: self._on_dap_started(dap))
            except Exception as exc:
                self._schedule_ui(lambda e=exc: self._on_dap_failed(e))  # type: ignore[misc]

        threading.Thread(target=_launch, daemon=True, name="console-dap-launch").start()

    def _retry_startup(self) -> None:
        """Rebuild the analysis (if we can) and try to launch the DAP again."""
        self._hide_retry()
        self._analysis_waited_ms = 0
        self._append_output("Retrying...\n", "progress")
        if self._on_retry_analysis is not None:
            try:
                self._on_retry_analysis()
            except Exception as exc:
                self._append_output(f"Retry failed: {exc}\n", "error")
        self._start_dap()

    def _stop_dap(self) -> None:
        if self._dap is not None:
            try:
                self._dap.terminate()
            except Exception:
                pass
            self._dap = None

    def _send(
        self,
        command: str,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[bool, str]:
        try:
            from pyrung.dap.live import send_command

            return send_command(self._session_name, command, on_progress=on_progress)
        except FileNotFoundError:
            return False, "Session not available (DAP may still be starting)"
        except (ConnectionRefusedError, OSError, EOFError) as exc:
            # EOFError is what a killed DAP looks like mid-command: the socket
            # closes before the result frame arrives.
            return False, f"Connection failed: {exc}"

    def _animate_prompt(self) -> None:
        if self._destroyed or self._busy_tick < 0:
            return
        dots = (self._busy_tick % 3) + 1
        self._prompt_label.configure(text="." * dots + " " * (3 - dots))
        self._busy_tick += 1
        self.after(400, self._animate_prompt)

    def _request_stop(self) -> None:
        """Ask the live session to cancel the in-flight command."""
        if self._cancel_requested:
            return
        self._cancel_requested = True
        self._send_btn.configure(state="disabled")
        self._append_output("Stopping...\n", "progress")

        def _worker() -> None:
            ok, text = self._send("stop")
            if not ok:
                self._schedule_ui(lambda: self._append_output(f"{text}\n", "error"))

        threading.Thread(target=_worker, daemon=True, name="console-stop").start()

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self._busy_tick = 0
            self._console_input.set_busy(True)
            # Repurpose Send as Stop rather than greying it out -- it's the
            # control the user's hand is already on.
            self._send_btn.configure(text="Stop", state="normal", command=self._request_stop)
            self._animate_prompt()
        else:
            self._busy_tick = -1
            self._prompt_label.configure(text=">>>")
            self._console_input.set_busy(False)
            self._send_btn.configure(
                text="Send", state="normal", command=self._console_input.submit
            )

    # ------------------------------------------------------------------
    # Command dispatch via pyrung live
    # ------------------------------------------------------------------

    def _submit_command_text(self, command: str) -> None:
        """Called by ConsoleInput when the user submits a command."""
        self._append_output(f">>> {command}\n", "prompt")
        self._cancel_requested = False
        self._set_busy(True)

        subs = [s.strip() for s in command.split(";") if s.strip()]

        def _on_progress(text: str) -> None:
            self._schedule_ui(lambda: self._append_output(text, "progress"))

        def _run() -> list[tuple[bool, str]]:
            results: list[tuple[bool, str]] = []
            for sub in subs:
                ok, text = self._send(sub, on_progress=_on_progress)
                results.append((ok, text))
                if not ok:
                    break
            return results

        def _done(results: list[tuple[bool, str]]) -> None:
            for ok, text in results:
                if not text:
                    continue
                if ok:
                    tag = "output"
                else:
                    # A stop we asked for isn't a failure -- don't shout it in red.
                    tag = "progress" if self._cancel_requested else "error"
                self._append_output(text + "\n", tag)
            self._cancel_requested = False
            self._set_busy(False)

        def _worker() -> None:
            try:
                results = _run()
            except Exception as exc:  # never leave the console stuck busy
                results = [(False, f"Console error: {exc}")]
            self._schedule_ui(lambda: _done(results))

        threading.Thread(target=_worker, daemon=True, name="console-cmd").start()

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _show_help(self) -> None:
        self._submit_command_text("help")

    def _open_project_folder(self) -> None:
        analysis = self._get_analysis()
        if analysis is None or not analysis.is_available:
            return
        project_dir = analysis.project_dir
        if project_dir is not None and project_dir.is_dir():
            os.startfile(project_dir)

    def _stop_file_watcher(self) -> None:
        if self._file_watch_after_id is not None:
            try:
                self.after_cancel(self._file_watch_after_id)
            except Exception:
                pass
            self._file_watch_after_id = None

    # ------------------------------------------------------------------
    # PLC data file browsing + watching
    # ------------------------------------------------------------------

    def _browse_plc_data(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Load PLC Data",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        self._plc_data_path = Path(path)
        self._plc_data_var.set(path)
        self._stop_file_watcher()
        self._append_output(f"Loading PLC data: {path}\n", "output")
        self._stop_dap()
        self._start_dap()

    # ------------------------------------------------------------------
    # Tag provider for autocomplete
    # ------------------------------------------------------------------

    def _provide_filtered_tags(self, search_text: str) -> list[str]:
        tags: frozenset[str] | set[str] = frozenset()
        if self._dap is not None:
            tags = self._dap.known_tags
        if not tags:
            analysis = self._get_analysis()
            if analysis is not None and analysis.is_available:
                tags = set(analysis.tag_to_addr_key.keys())
        if not tags:
            return []
        candidates = sorted(tags)
        if self._filter_func is not None:
            return self._filter_func(candidates, search_text)
        search_upper = search_text.strip().upper()
        if not search_upper:
            return candidates
        return [t for t in candidates if search_upper in t.upper()]

    # ------------------------------------------------------------------
    # Widget creation
    # ------------------------------------------------------------------

    def _create_widgets(self) -> None:
        # Toolbar row: PLC Data + Help
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.pack(fill=tk.X)

        ttk.Label(toolbar, text="PLC Data:").pack(side=tk.LEFT, padx=(0, 4))
        self._plc_data_var = tk.StringVar()
        plc_entry = ttk.Entry(toolbar, textvariable=self._plc_data_var, state="readonly")
        plc_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(toolbar, text="Browse...", width=8, command=self._browse_plc_data).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(toolbar, text="Help", width=6, command=self._show_help).pack(side=tk.LEFT)

        ttk.Button(
            toolbar,
            text="\N{OPEN FILE FOLDER}",
            width=3,
            command=self._open_project_folder,
        ).pack(side=tk.LEFT, padx=(4, 0))

        # Packed only while startup is in a failed state (see _show_retry).
        self._retry_btn = ttk.Button(toolbar, text="Retry", width=6, command=self._retry_startup)

        # Input row (at top, before output)
        input_frame = ttk.Frame(self, padding=(8, 0, 8, 6))
        input_frame.pack(fill=tk.X)

        self._prompt_label = ttk.Label(input_frame, text=">>>")
        self._prompt_label.pack(side=tk.LEFT, padx=(0, 4))
        self._console_input = ConsoleInput(
            input_frame,
            completer=self._completer,
            tag_provider=self._provide_filtered_tags,
            on_submit=self._submit_command_text,
        )
        self._console_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._send_btn = ttk.Button(
            input_frame, text="Send", width=6, command=self._console_input.submit
        )
        self._send_btn.pack(side=tk.LEFT)

        # Status bar. Packed against the bottom *before* the output area: the
        # output Text asks for its natural 24-line height, which oversubscribes
        # the window, and pack starves whatever was packed last.
        self._status_var = tk.StringVar(value="Starting...")
        status_bar = ttk.Frame(self, padding=(8, 2, 8, 4))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self._copy_btn = ttk.Button(
            status_bar, text=_COPY_LABEL, width=8, command=self._copy_output
        )
        self._copy_btn.pack(side=tk.RIGHT)
        bind_tooltip(self._copy_btn, "Copy output (or the current selection) to the clipboard")
        ttk.Label(status_bar, textvariable=self._status_var, foreground="gray").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        # Output area
        output_frame = ttk.Frame(self)
        output_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self._output = tk.Text(
            output_frame,
            wrap=tk.WORD,
            state="disabled",
            height=10,
            font=("Consolas", 10),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            relief=tk.FLAT,
            borderwidth=0,
            padx=8,
            pady=6,
        )
        scrollbar = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self._output.yview)
        self._output.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._output.tag_configure("prompt", foreground="#569cd6")
        self._output.tag_configure("error", foreground="#f44747")
        self._output.tag_configure("output", foreground="#d4d4d4")
        self._output.tag_configure("progress", foreground="#808080")

        self._console_input.focus_set()

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._stop_file_watcher()
        if self._analysis_after_id is not None:
            try:
                self.after_cancel(self._analysis_after_id)
            except Exception:
                pass
            self._analysis_after_id = None
        self._stop_dap()
        if self._on_destroy:
            self._on_destroy()
        self.destroy()

    def _load_grammar(self) -> None:
        def _load() -> None:
            try:
                self._completer.load_grammar()
            except Exception:
                pass

        threading.Thread(target=_load, daemon=True, name="console-grammar").start()

    def __init__(
        self,
        parent: tk.Widget,
        *,
        get_store: Callable[[], AddressStore | None],
        get_analysis: Callable[[], AnalysisService | None],
        get_click_hwnd: Callable[[], int | None],
        get_mdb_path: Callable[[], Path | None],
        get_synced_pending: Callable[[], int],
        filter_func: Callable[[list[str], str], list[str]] | None = None,
        on_destroy: Callable[[], None] | None = None,
        on_retry_analysis: Callable[[], None] | None = None,
        title_suffix: str = "",
        session_name: str = "clicknick",
    ) -> None:
        super().__init__(parent)
        self._get_store = get_store
        self._get_analysis = get_analysis
        self._get_click_hwnd = get_click_hwnd
        self._get_mdb_path = get_mdb_path
        self._get_synced_pending = get_synced_pending
        self._filter_func = filter_func
        self._on_destroy = on_destroy
        self._on_retry_analysis = on_retry_analysis

        self.title(f"Console — {title_suffix}" if title_suffix else "Console")
        self.geometry("750x500")
        self.minsize(500, 300)

        self._session_name = session_name
        self._dap: Any | None = None
        self._plc_data_path: Path | None = None
        self._plc_data_mtime: float = 0.0
        self._file_watch_after_id: str | None = None
        self._copy_flash_after_id: str | None = None
        self._analysis_after_id: str | None = None
        self._analysis_waited_ms: int = 0
        self._launch_generation: int = -1
        self._busy_tick: int = -1
        self._cancel_requested = False
        self._destroyed = False
        self._completer = ConsoleCompleter()

        self._create_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_dap()
        self._load_grammar()

    def _poll_analysis(self) -> None:
        self._analysis_after_id = None
        if self._destroyed:
            return

        analysis = self._get_analysis()
        if analysis is not None and analysis.is_available:
            self._start_dap()
            return

        from ..services.analysis_service import AnalysisStatus

        if analysis is not None and analysis.status is AnalysisStatus.FAILED:
            self._report_startup_failure(
                analysis.error or "converting the program to pyrung failed.",
                analysis.error_detail,
            )
            return

        self._wait_for_analysis()

    def _on_dap_started(self, dap: Any) -> None:
        self._dap = dap
        # Confirm success in the transcript. Without it a "Retrying..." or
        # "Reloading..." line just trails off with no visible outcome.
        self._append_output("OK - simulation ready.\n", "progress")
        self._hide_retry()
        self._status_var.set("Paused")
        self._start_file_watcher()

    def _start_file_watcher(self) -> None:
        if self._plc_data_path is None:
            return
        try:
            self._plc_data_mtime = os.path.getmtime(self._plc_data_path)
        except OSError:
            self._plc_data_mtime = 0.0
        self._file_watch_after_id = self.after(_PLC_DATA_WATCH_MS, self._check_plc_data_changed)

    def _check_plc_data_changed(self) -> None:
        if self._destroyed or self._plc_data_path is None:
            return
        try:
            current_mtime = os.path.getmtime(self._plc_data_path)
            if current_mtime > self._plc_data_mtime:
                self._plc_data_mtime = current_mtime
                self._append_output("PLC data file changed. Reloading...\n", "output")
                self._stop_dap()
                self._start_dap()
        except OSError:
            pass
        self._file_watch_after_id = self.after(_PLC_DATA_WATCH_MS, self._check_plc_data_changed)
