"""The Simulator's command console: a bottom pane that pops out into its own window.

It observes the connection's SimulationSession like the rest of the Simulator,
and sends commands to the pyrung LiveServer via ``pyrung.dap.live.send_command()``.
The Simulator owns the transcript and command history, so both survive moving
the console between its pane and its own window. Start, Retry and the PLC data
file live on the Simulator's toolbar and banners, not here.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk
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
_DIVIDER = "#c8c8c8"
_DIVIDER_ACTIVE = "#0078d4"

#: Everything the console has printed, as (text, tag) pieces, oldest first.
Transcript = list[tuple[str, str | None]]


class ConsolePanel(ttk.Frame):
    """Transcript over a command line, under a slim header of console actions."""

    def _start_background(self, target: Callable[[], None], *, name: str) -> None:
        """Start a named daemon worker."""
        threading.Thread(target=target, daemon=True, name=name).start()

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _write(self, text: str, tag: str | None) -> None:
        self._output.configure(state="normal")
        if tag:
            self._output.insert(tk.END, text, tag)
        else:
            self._output.insert(tk.END, text)
        self._output.configure(state="disabled")
        self._output.see(tk.END)

    def _append_output(self, text: str, tag: str | None = None) -> None:
        self._transcript.append((text, tag))
        self._write(text, tag)

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
    # Simulation events (the SimulationSession owns the DAP)
    # ------------------------------------------------------------------

    def _on_simulation_event(self, event: SimEvent) -> None:
        if self._destroyed:
            return
        if event.kind == "message":
            self._append_output(event.text.rstrip("\n") + "\n", event.level)
        elif event.kind == "echo":
            # What the user just did on the panel, as the command that does it.
            self._append_output(f"# {event.text}\n", "echo")

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
        # A command's output arrives in this panel, so it stays put until done.
        self._pop_btn.configure(state="disabled" if busy else "normal")
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
    # Header actions
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

    def _header_button(
        self, header: ttk.Frame, text: str, command: Callable[[], None], tip: str
    ) -> ttk.Button:
        """A flat header action (VS Code panel style) that still looks clickable on hover."""
        button = ttk.Button(header, text=text, style="Toolbutton", cursor="hand2", command=command)
        button.pack(side=tk.RIGHT)
        bind_tooltip(button, tip)
        return button

    def _set_divider_active(self, active: bool) -> None:
        if not self._destroyed:
            self._divider.configure(background=_DIVIDER_ACTIVE if active else _DIVIDER)

    def _bind_resize(self, handles: tuple[ttk.Frame | ttk.Label, ...]) -> None:
        """Dragging the header resizes the pane, like the sash just above it."""
        on_resize = self._on_resize
        assert on_resize is not None
        dragging = False

        def press(event: tk.Event) -> None:
            nonlocal dragging
            dragging = True
            on_resize(event.y_root, True)

        def release(_event: tk.Event) -> None:
            nonlocal dragging
            dragging = False
            self._set_divider_active(False)

        for handle in handles:
            handle.configure(cursor="sb_v_double_arrow")
            handle.bind("<ButtonPress-1>", press)
            handle.bind("<B1-Motion>", lambda e: on_resize(e.y_root, False))
            handle.bind("<ButtonRelease-1>", release)
            handle.bind("<Enter>", lambda _e: self._set_divider_active(True))
            handle.bind("<Leave>", lambda _e: dragging or self._set_divider_active(False))

    def _create_widgets(self, *, popped: bool) -> None:
        # The pane's top edge; it lights up while the header can be dragged.
        self._divider = tk.Frame(self, height=1, background=_DIVIDER)
        self._divider.pack(fill=tk.X)
        # Header: what this pane is, then its actions, VS Code panel style.
        header = ttk.Frame(self, padding=(8, 2, 4, 2))
        header.pack(fill=tk.X)
        title = ttk.Label(header, text="CONSOLE", foreground="gray")
        title.pack(side=tk.LEFT)
        if self._on_resize is not None:
            self._bind_resize((header, title))
        if self._on_hide is not None:
            self._header_button(
                header, "\N{MULTIPLICATION SIGN}", self._on_hide, "Hide the console (Ctrl+`)"
            )
        if popped:
            pop = ("Dock", "Put the console back in the Simulator")
        else:
            pop = ("Pop out", "Move the console to its own window")
        self._pop_btn = self._header_button(header, pop[0], self._on_pop, pop[1])
        self._copy_btn = self._header_button(
            header, _COPY_LABEL, self._copy_output,
            "Copy output (or the current selection) to the clipboard",
        )  # fmt: skip
        self._header_button(
            header, "Workspace", self._open_project_folder, "Open the workspace folder"
        )
        self._header_button(header, "Help", self._show_help, "List the console's commands")

        # Command line at the bottom, terminal style. Packed before the output:
        # the Text asks for more height than a slim pane has, and pack starves
        # whatever was packed last.
        input_frame = ttk.Frame(self, padding=(8, 4, 8, 6))
        input_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self._prompt_label = ttk.Label(input_frame, text=">>>")
        self._prompt_label.pack(side=tk.LEFT, padx=(0, 4))
        self._console_input = ConsoleInput(
            input_frame,
            completer=self._completer,
            tag_provider=self._provide_filtered_tags,
            on_submit=self._submit_command_text,
            history=self._history,
        )
        self._console_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._send_btn = ttk.Button(
            input_frame, text="Send", width=6, command=self._console_input.submit
        )
        self._send_btn.pack(side=tk.LEFT)

        output_frame = ttk.Frame(self)
        output_frame.pack(fill=tk.BOTH, expand=True, padx=8)
        self._output = tk.Text(
            output_frame,
            wrap=tk.WORD,
            state="disabled",
            height=5,
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
        self._output.tag_configure("echo", foreground="#6a9955")

    def _load_grammar(self) -> None:
        def _load() -> None:
            try:
                self._completer.load_grammar()
            except Exception:
                pass

        self._start_background(_load, name="console-grammar")

    def __init__(
        self,
        parent: tk.Misc,
        *,
        simulation: SimulationSession,
        get_analysis: Callable[[], AnalysisService | None],
        transcript: Transcript,
        history: list[str],
        on_pop: Callable[[], None],
        popped: bool = False,
        on_hide: Callable[[], None] | None = None,
        on_resize: Callable[[int, bool], None] | None = None,
        filter_func: Callable[[list[str], str], list[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._simulation = simulation
        self._get_analysis = get_analysis
        self._transcript = transcript
        self._history = history
        self._on_pop = on_pop
        self._on_hide = on_hide
        # Called with the pointer's screen y as the header is pressed (True) and dragged.
        self._on_resize = on_resize
        self._filter_func = filter_func

        self._copy_flash_after_id: str | None = None
        self._busy_tick: int = -1
        self._cancel_requested = False
        self._destroyed = False
        self._completer = ConsoleCompleter()

        self._create_widgets(popped=popped)
        for text, tag in transcript:
            self._write(text, tag)
        simulation.add_listener(self._on_simulation_event)
        self._load_grammar()

    @property
    def busy(self) -> bool:
        """A command is in flight; its output will arrive in this panel."""
        return self._busy_tick >= 0

    def focus_input(self) -> None:
        self._console_input.focus_set()

    def run(self, command: str) -> bool:
        """Run *command* as if typed (it joins the history); False while one is running."""
        if self.busy or self._destroyed:
            return False
        self._console_input.remember(command)
        self._submit_command_text(command)
        return True

    def close(self) -> None:
        """Stop following the simulation and destroy the panel."""
        if self._destroyed:
            return
        self._destroyed = True
        self._simulation.remove_listener(self._on_simulation_event)
        self.destroy()


class ConsoleWindow(tk.Toplevel):
    """The console popped out of the Simulator; closing it docks it back."""

    def __init__(
        self, parent: tk.Misc, *, title: str, on_dock: Callable[[], None], **panel_options
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("750x400")
        self.minsize(400, 200)
        self.panel = ConsolePanel(self, on_pop=on_dock, popped=True, **panel_options)
        self.panel.pack(fill=tk.BOTH, expand=True)
        self.protocol("WM_DELETE_WINDOW", on_dock)
        self.panel.focus_input()
