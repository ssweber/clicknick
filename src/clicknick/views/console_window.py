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

from ..widgets.nickname_combobox import NicknameCombobox

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..data.address_store import AddressStore
    from ..services.analysis_service import AnalysisService

_SESSION_NAME = "clicknick"
_PLC_DATA_WATCH_MS = 2000
_ANALYSIS_POLL_MS = 500
_MAX_HISTORY = 200


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

    def _on_dap_failed(self, exc: Exception) -> None:
        self._append_output(f"DAP failed: {exc}\n", "error")
        self._status_var.set("Error")

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

    # ------------------------------------------------------------------
    # DAP lifecycle
    # ------------------------------------------------------------------

    def _start_dap(self) -> None:
        analysis = self._get_analysis()
        if analysis is None or not analysis.is_available:
            self._status_var.set("Building program analysis...")
            self.after(_ANALYSIS_POLL_MS, self._poll_analysis)
            return

        project_dir = analysis.project_dir
        if project_dir is None or not project_dir.is_dir():
            self._append_output("No pyrung project directory found.\n", "error")
            self._status_var.set("No project")
            return

        self._status_var.set("Starting...")
        snapshot_path = self._plc_data_path

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
                    session_name=_SESSION_NAME,
                )
                self._schedule_ui(lambda: self._on_dap_started(dap))
            except Exception as exc:
                self._schedule_ui(lambda e=exc: self._on_dap_failed(e))  # type: ignore[misc]

        threading.Thread(target=_launch, daemon=True, name="console-dap-launch").start()

    def _stop_dap(self) -> None:
        if self._dap is not None:
            try:
                self._dap.terminate()
            except Exception:
                pass
            self._dap = None

    def _send(self, command: str) -> tuple[bool, str]:
        try:
            from pyrung.dap.live import send_command

            return send_command(_SESSION_NAME, command)
        except FileNotFoundError:
            return False, "Session not available (DAP may still be starting)"
        except (ConnectionRefusedError, OSError) as exc:
            return False, f"Connection failed: {exc}"

    def _animate_prompt(self) -> None:
        if self._destroyed or self._busy_tick < 0:
            return
        dots = (self._busy_tick % 3) + 1
        self._prompt_label.configure(text="." * dots + " " * (3 - dots))
        self._busy_tick += 1
        self.after(400, self._animate_prompt)

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self._busy_tick = 0
            self._input_entry.configure(state="disabled")
            self._send_btn.configure(state="disabled")
            self._animate_prompt()
        else:
            self._busy_tick = -1
            self._prompt_label.configure(text=">>>")
            self._input_entry.configure(state="normal")
            self._send_btn.configure(state="normal")
            self._input_entry.focus_set()

    # ------------------------------------------------------------------
    # Command dispatch via pyrung live
    # ------------------------------------------------------------------

    def _submit_command(self) -> None:
        command = self._input_var.get().strip()
        if not command:
            return
        self._input_var.set("")

        if not self._history or self._history[-1] != command:
            self._history.append(command)
            if len(self._history) > _MAX_HISTORY:
                self._history.pop(0)
        self._history_idx = len(self._history)

        self._append_output(f">>> {command}\n", "prompt")
        self._set_busy(True)

        subs = [s.strip() for s in command.split(";") if s.strip()]

        def _run() -> list[tuple[bool, str]]:
            results: list[tuple[bool, str]] = []
            for sub in subs:
                ok, text = self._send(sub)
                results.append((ok, text))
                if not ok:
                    break
            return results

        def _done(results: list[tuple[bool, str]]) -> None:
            for ok, text in results:
                if text:
                    self._append_output(text + "\n", "output" if ok else "error")
            self._set_busy(False)

        def _worker() -> None:
            results = _run()
            self._schedule_ui(lambda: _done(results))

        threading.Thread(target=_worker, daemon=True, name="console-cmd").start()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _history_prev(self) -> None:
        if not self._history:
            return
        self._history_idx = max(0, self._history_idx - 1)
        self._input_var.set(self._history[self._history_idx])
        self._input_entry.icursor(tk.END)

    def _history_next(self) -> None:
        if not self._history:
            return
        self._history_idx = min(len(self._history), self._history_idx + 1)
        if self._history_idx == len(self._history):
            self._input_var.set("")
        else:
            self._input_var.set(self._history[self._history_idx])
        self._input_entry.icursor(tk.END)

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _show_help(self) -> None:
        self._input_var.set("help")
        self._submit_command()

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
    # Nickname insert
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

    def _on_tag_selected(self, tag_name: str) -> None:
        if not tag_name:
            return
        current = self._input_var.get()
        cursor = self._input_entry.index(tk.INSERT)
        new_text = current[:cursor] + tag_name + current[cursor:]
        self._input_var.set(new_text)
        self._input_entry.icursor(cursor + len(tag_name))
        self._input_entry.focus_set()
        self._nickname_combo.reset()

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

        # Nickname row
        nick_row = ttk.Frame(self, padding=(8, 0, 8, 6))
        nick_row.pack(fill=tk.X)

        ttk.Label(nick_row, text="Nickname:").pack(side=tk.LEFT, padx=(0, 4))
        combo_frame = ttk.Frame(nick_row)
        combo_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        combo_frame.withdraw = lambda: None  # type: ignore[attr-defined]

        self._nickname_combo = NicknameCombobox(combo_frame, width=30, skip_address_check=True)
        self._nickname_combo.pack(fill=tk.X, expand=True)
        self._nickname_combo.set_data_provider(self._provide_filtered_tags)
        self._nickname_combo.set_selection_callback(self._on_tag_selected)

        ttk.Button(
            nick_row, text="Insert", width=8, command=self._nickname_combo.finalize_entry
        ).pack(side=tk.LEFT)

        # Output area
        output_frame = ttk.Frame(self)
        output_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self._output = tk.Text(
            output_frame,
            wrap=tk.WORD,
            state="disabled",
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

        # Input row
        input_frame = ttk.Frame(self, padding=(8, 0, 8, 6))
        input_frame.pack(fill=tk.X)

        self._prompt_label = ttk.Label(input_frame, text=">>>")
        self._prompt_label.pack(side=tk.LEFT, padx=(0, 4))
        self._input_var = tk.StringVar()
        self._input_entry = ttk.Entry(input_frame, textvariable=self._input_var)
        self._input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._input_entry.bind("<Return>", lambda _: self._submit_command())
        self._input_entry.bind("<Up>", lambda _: self._history_prev())
        self._input_entry.bind("<Down>", lambda _: self._history_next())
        self._send_btn = ttk.Button(input_frame, text="Send", width=6, command=self._submit_command)
        self._send_btn.pack(side=tk.LEFT)

        # Status bar
        self._status_var = tk.StringVar(value="Starting...")
        status_bar = ttk.Frame(self, padding=(8, 2, 8, 4))
        status_bar.pack(fill=tk.X)
        ttk.Label(status_bar, textvariable=self._status_var, foreground="gray").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        self._input_entry.focus_set()

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._stop_file_watcher()
        self._stop_dap()
        if self._on_destroy:
            self._on_destroy()
        self.destroy()

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
        title_suffix: str = "",
    ) -> None:
        super().__init__(parent)
        self._get_store = get_store
        self._get_analysis = get_analysis
        self._get_click_hwnd = get_click_hwnd
        self._get_mdb_path = get_mdb_path
        self._get_synced_pending = get_synced_pending
        self._filter_func = filter_func
        self._on_destroy = on_destroy

        self.title(f"Console — {title_suffix}" if title_suffix else "Console")
        self.geometry("750x500")
        self.minsize(500, 300)

        self._dap: Any | None = None
        self._plc_data_path: Path | None = None
        self._plc_data_mtime: float = 0.0
        self._file_watch_after_id: str | None = None
        self._history: list[str] = []
        self._history_idx: int = 0
        self._busy_tick: int = -1
        self._destroyed = False

        self._create_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_dap()

    def _poll_analysis(self) -> None:
        if self._destroyed:
            return
        analysis = self._get_analysis()
        if analysis is not None and analysis.is_available:
            self._start_dap()
        else:
            self.after(_ANALYSIS_POLL_MS, self._poll_analysis)

    def _on_dap_started(self, dap: Any) -> None:
        self._dap = dap
        dap.continue_()
        self._status_var.set("Running")
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
