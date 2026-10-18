"""Interactive pyrung simulation console.

Singleton window accessible from Tools > Console. It observes the connection's
SimulationSession (which owns the pyrung DAP subprocess), shared with the
Simulator window. Opening either turns the simulation on; closing them does
not turn it off (the main window's Simulation toggle does). Commands go to the
pyrung LiveServer via ``pyrung.dap.live.send_command()``.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING

from ..services.console_completer import ConsoleCompleter
from ..widgets.console_input import ConsoleInput
from ..widgets.tooltip import bind_tooltip

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..services.analysis_service import AnalysisService
    from ..simulation_session import SimEvent, SimulationSession

_COPY_FLASH_MS = 1200
# Plain text, not a clipboard emoji: the emoji renders in colour from a
# different font and sits oddly among ttk's monochrome controls.
_COPY_LABEL = "Copy"
_COPIED_LABEL = "Copied"


class ConsoleWindow(tk.Toplevel):
    """Interactive pyrung simulation console."""

    def _start_background(self, target: Callable[[], None], *, name: str) -> None:
        """Start a named daemon worker."""
        threading.Thread(target=target, daemon=True, name=name).start()

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
    # Simulation status (the SimulationSession owns the DAP)
    # ------------------------------------------------------------------

    def _show_retry(self) -> None:
        if not self._retry_btn.winfo_manager():
            self._retry_btn.pack(side=tk.LEFT, padx=(4, 0))

    def _hide_retry(self) -> None:
        if self._retry_btn.winfo_manager():
            self._retry_btn.pack_forget()
        self._details_btn.pack_forget()

    def _show_startup_details(self) -> None:
        detail = self._simulation.error_detail
        if detail:
            self._append_output(detail.rstrip() + "\n", "progress")
        self._details_btn.pack_forget()
        self._details_shown_for = detail

    def _retry_startup(self) -> None:
        """Rebuild the analysis (if we can) and launch the simulation again."""
        self._details_shown_for = None
        self._simulation.retry()

    def _refresh_status(self) -> None:
        from ..simulation_session import SimStatus

        sim = self._simulation
        self._status_var.set(sim.status_text)
        # The Simulator can load PLC data too; both show the session's file.
        plc_data = sim.plc_data_path
        self._plc_data_var.set(str(plc_data) if plc_data is not None else "")
        if not sim.enabled:
            # Turned off from the main window: the console stays, ready to start it again.
            self._retry_btn.configure(text="Start", command=sim.turn_on)
            self._show_retry()
            self._details_btn.pack_forget()
        elif sim.status is SimStatus.FAILED:
            self._retry_btn.configure(text="Retry", command=self._retry_startup)
            self._show_retry()
            if sim.error_detail and self._details_shown_for != sim.error_detail:
                if not self._details_btn.winfo_manager():
                    self._details_btn.pack(side=tk.RIGHT, padx=(0, 4))
            else:
                self._details_btn.pack_forget()
        else:
            self._hide_retry()

    def _on_simulation_event(self, event: SimEvent) -> None:
        if self._destroyed:
            return
        if event.kind == "message":
            self._append_output(event.text.rstrip("\n") + "\n", event.level)
        if event.kind in ("status", "frame", "message"):
            self._refresh_status()

    def _schedule_ui(self, callback: Callable[[], None]) -> None:
        if self._destroyed:
            return
        try:
            self.after(0, callback)
        except tk.TclError:
            pass

    def _send(
        self,
        command: str,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[bool, str]:
        try:
            from pyrung.dap.live import send_command

            return send_command(self._simulation.session_name, command, on_progress=on_progress)
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

        self._start_background(_worker, name="console-stop")

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

        self._start_background(_worker, name="console-cmd")

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _show_help(self) -> None:
        self._submit_command_text("help")

    def _open_project_folder(self) -> None:
        analysis = self._get_analysis()
        if analysis is None:
            return
        project_dir = analysis.project_dir
        if project_dir is not None and project_dir.is_dir():
            os.startfile(project_dir)

    # ------------------------------------------------------------------
    # PLC data file browsing (the simulation watches it for changes)
    # ------------------------------------------------------------------

    def _browse_plc_data(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Load PLC Data",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        self._simulation.set_plc_data_path(Path(path))

    # ------------------------------------------------------------------
    # Tag provider for autocomplete
    # ------------------------------------------------------------------

    def _provide_filtered_tags(self, search_text: str) -> list[str]:
        tags: frozenset[str] | set[str] = self._simulation.known_tags
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
        browse_btn = ttk.Button(toolbar, text="Browse...", width=8, command=self._browse_plc_data)
        browse_btn.pack(side=tk.LEFT, padx=(0, 4))
        bind_tooltip(
            browse_btn,
            "Start from the PLC's live values: a CSV saved in CLICK with\n"
            "PLC > Read Data from PLC > All > Save (not the nickname CSV)",
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
        self._details_btn = ttk.Button(
            status_bar, text="Show details", command=self._show_startup_details
        )
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
        self._simulation.remove_listener(self._on_simulation_event)
        if self._on_destroy:
            self._on_destroy()
        self.destroy()

    def _load_grammar(self) -> None:
        def _load() -> None:
            try:
                self._completer.load_grammar()
            except Exception:
                pass

        self._start_background(_load, name="console-grammar")

    def __init__(
        self,
        parent: tk.Widget,
        *,
        simulation: SimulationSession,
        get_analysis: Callable[[], AnalysisService | None],
        filter_func: Callable[[list[str], str], list[str]] | None = None,
        on_destroy: Callable[[], None] | None = None,
        title_suffix: str = "",
    ) -> None:
        super().__init__(parent)
        self._simulation = simulation
        self._get_analysis = get_analysis
        self._filter_func = filter_func
        self._on_destroy = on_destroy

        self.title(f"Console — {title_suffix}" if title_suffix else "Console")
        self.geometry("750x500")
        self.minsize(500, 300)

        self._copy_flash_after_id: str | None = None
        # The failure whose details were already printed, so the button hides.
        self._details_shown_for: str | None = None
        self._busy_tick: int = -1
        self._cancel_requested = False
        self._destroyed = False
        self._completer = ConsoleCompleter()

        self._create_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # The opener turns the simulation on after this, so its startup lands
        # in the transcript. Closing the console leaves the simulation running.
        simulation.add_listener(self._on_simulation_event)
        self._refresh_status()
        self._load_grammar()
