"""Program analysis report window.

Rule identity, order, titles, severity, and the *shape* of each finding are all
owned by pyrung: rules come from its validation registry (``ordered_rules()``)
and every finding hands over a presentation-ready ``FindingDisplay`` modelled on a
Python traceback — one or more *frames* (a compact ``Main:R5`` location, the
offending code as written, and an optional caret span), a one-line *problem*, and an
optional *hint*.  This window just styles that structure; it does no message
parsing.  The only display knowledge clicknick owns is the severity palette.

Frames render in a monospace font with the caret line built from literal spaces, so
the caret aligns exactly under the offending token in the code above it.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ..services.program_check_preferences import ProgramCheckPreferences

if TYPE_CHECKING:
    from pyrung.core.validation import FindingDisplay

# Severity -> (text colour, leading glyph).  Severities come from pyrung's
# registry; this palette is the only display knowledge clicknick owns.
_SEVERITY_STYLE = {
    "error": ("#B22222", "✕"),  # ✕
    "warning": ("#CC6600", "⚠"),  # ⚠
    "info": ("#1E6FB8", "ℹ"),  # ℹ
    "advisory": ("#777777", "•"),  # •
}
_PASS_COLOR = "#228B22"
_PASS_GLYPH = "✓"  # ✓
_MUTED = "#888888"

# Plain text, not a clipboard emoji: the emoji renders in colour from a
# different font and sits oddly among ttk's monochrome controls.
_COPY_LABEL = "Copy Full Report"
_COPIED_LABEL = "Copied"
_COPY_FLASH_MS = 1200
_PASSED_SECTION = "__passed__"


@dataclass
class AnalysisReportData:
    """View model for the analysis report: rule code -> its FindingDisplays."""

    grouped_findings: dict[str, list[FindingDisplay]] = field(default_factory=dict)
    project_name: str = ""


def _rule_rows(grouped: dict[str, list[FindingDisplay]]) -> list[tuple[str, str, str]]:
    """`(code, title, severity)` rows in display order, straight from the registry.

    Registry rules come first in canonical (severity-desc) order; any finding
    whose code the installed pyrung doesn't know is appended — never dropped —
    with the raw code as its title. Future severities use warning styling.
    """
    from pyrung.core.validation import ordered_rules

    specs = ordered_rules()
    known = {s.code for s in specs}
    rows = [(s.code, s.title, s.severity) for s in specs]
    rows += [
        (code, code, grouped[code][0].severity if grouped[code] else "warning")
        for code in sorted(grouped)
        if code not in known
    ]
    return [
        (code, title, sev if sev in _SEVERITY_STYLE else "warning") for code, title, sev in rows
    ]


class AnalysisReportWindow:
    def _count(self, code: str) -> int:
        return len(self._grouped.get(code, []))

    def _build_summary(
        self,
        parent: ttk.Frame,
        failing: list[tuple[str, str, str]],
        passing: list[tuple[str, str, str]],
        total_findings: int,
    ) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, pady=(0, 8))

        if total_findings == 0:
            ttk.Label(
                bar,
                text=f"{_PASS_GLYPH}  All checks passed",
                font=("Segoe UI", 12, "bold"),
                foreground=_PASS_COLOR,
            ).pack(side=tk.LEFT)
            self._summary_line = "All checks passed"
            return

        # One coloured chip per severity that actually occurs, most-severe first.
        by_sev: dict[str, int] = {}
        for code, _title, sev in failing:
            by_sev[sev] = by_sev.get(sev, 0) + self._count(code)

        chips: list[str] = []
        for sev in ("error", "warning", "info", "advisory"):
            n = by_sev.get(sev)
            if not n:
                continue
            color, glyph = _SEVERITY_STYLE[sev]
            label = sev if n == 1 else sev + "s"
            ttk.Label(
                bar,
                text=f"{glyph} {n} {label}",
                font=("Segoe UI", 11, "bold"),
                foreground=color,
            ).pack(side=tk.LEFT, padx=(0, 16))
            chips.append(f"{n} {label}")

        checked = len(failing) + len(passing)
        ttk.Label(
            bar,
            text=f"{len(passing)}/{checked} checks passed",
            font=("Segoe UI", 9),
            foreground=_MUTED,
        ).pack(side=tk.RIGHT)
        self._summary_line = f"{', '.join(chips)} - {len(passing)}/{checked} checks passed"

    def _focus_section(self, code: str) -> None:
        self._active_section = code
        header, _body, _expanded = self._sections[code]
        self._text.tag_remove("focused_header", "1.0", tk.END)
        start, end = self._text.tag_ranges(header)
        self._text.tag_add("focused_header", start, end)
        self._text.mark_set(tk.INSERT, start)

    def _move_section(self, direction: int) -> str:
        codes = list(self._sections)
        if codes:
            index = codes.index(self._active_section) if self._active_section in codes else -1
            self._focus_section(codes[max(0, min(index + direction, len(codes) - 1))])
            self._text.see(tk.INSERT)
        return "break"

    def _toggle_section(self, code: str, expanded: bool | None = None) -> str:
        header, body, current = self._sections[code]
        expanded = not current if expanded is None else expanded
        start = self._text.tag_ranges(header)[0]
        self._text.config(state=tk.NORMAL)
        self._text.delete(start, f"{start}+1c")
        self._text.insert(start, "v" if expanded else ">", header)
        self._text.config(state=tk.DISABLED)
        self._text.tag_configure(body, elide=not expanded)
        self._sections[code] = (header, body, expanded)
        self._focus_section(code)
        self._text.focus_set()
        saved = self._preferences.set_expanded(code, expanded)
        self._preference_status.configure(
            text=""
            if saved
            else "Could not save view preferences; remembered for this window only."
        )
        return "break"

    def _toggle_active(self, expanded: bool | None = None) -> str:
        if self._active_section in self._sections:
            self._toggle_section(self._active_section, expanded)
        return "break"

    def _build_text(self, parent: ttk.Frame) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(
            frame,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            height=10,
            padx=12,
            pady=10,
            cursor="arrow",
            borderwidth=1,
            relief=tk.SOLID,
            spacing1=1,
            spacing3=2,
        )
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text.tag_configure("section", font=("Segoe UI", 9, "bold"), foreground=_MUTED, spacing1=8)
        # A shared problem lead line (multi-site findings / contradictions).
        text.tag_configure(
            "problem",
            font=("Segoe UI", 10),
            foreground="#1A1A1A",
            lmargin1=30,
            lmargin2=30,
            spacing1=6,
        )
        # The "--> location" line of a frame — monospace, muted.
        text.tag_configure(
            "floc",
            font=("Consolas", 10),
            foreground=_MUTED,
            lmargin1=28,
            lmargin2=28,
            spacing1=6,
        )
        # The "|" rail + code lines — monospace so the caret aligns under the token.
        text.tag_configure(
            "rail",
            font=("Consolas", 10),
            foreground="#333333",
            lmargin1=28,
            lmargin2=28,
        )
        # The caret line (rail + ^^^ + label) — coloured per severity.  One per severity.
        for sev, (color, _glyph) in _SEVERITY_STYLE.items():
            text.tag_configure(
                f"caret_{sev}",
                font=("Consolas", 10),
                foreground=color,
                lmargin1=28,
                lmargin2=28,
            )
        # The "= hint:" line — monospace italic blue, "try this instead".
        text.tag_configure(
            "hint",
            font=("Consolas", 10, "italic"),
            foreground="#1E6FB8",
            lmargin1=28,
            lmargin2=28,
            spacing1=2,
        )
        text.tag_configure("pass", foreground=_PASS_COLOR, lmargin1=16, lmargin2=30)
        text.tag_configure("pass_muted", foreground=_MUTED, lmargin1=16, lmargin2=30)
        text.tag_configure("focused_header", background="#E8EEF7")
        text.bind("<Up>", lambda _e: self._move_section(-1))
        text.bind("<Down>", lambda _e: self._move_section(1))
        text.bind("<Left>", lambda _e: self._toggle_active(False))
        text.bind("<Right>", lambda _e: self._toggle_active(True))
        text.bind("<Return>", lambda _e: self._toggle_active())
        text.bind("<space>", lambda _e: self._toggle_active())
        return text

    def _insert_section_header(
        self, text: tk.Text, code: str, label: str, style: str, *, default: bool = True
    ) -> str:
        index = len(self._sections)
        header, body = f"header_{index}", f"body_{index}"
        expanded = self._preferences.is_expanded(code, default=default)
        self._sections[code] = (header, body, expanded)
        marker = "v" if expanded else ">"
        text.insert(tk.END, f"{marker}  {label}\n", (style, header))
        text.tag_configure(body, elide=not expanded)
        text.tag_bind(header, "<Button-1>", lambda _e: self._toggle_section(code))
        text.tag_bind(header, "<Enter>", lambda _e: text.configure(cursor="hand2"))
        text.tag_bind(header, "<Leave>", lambda _e: text.configure(cursor="arrow"))
        return body

    @staticmethod
    def _ensure_rule_tag(text: tk.Text, rule_tag: str, severity: str) -> None:
        color, _glyph = _SEVERITY_STYLE.get(severity, _SEVERITY_STYLE["warning"])
        text.tag_configure(rule_tag, foreground=color, font=("Segoe UI", 10, "bold"), spacing1=10)

    @staticmethod
    def _insert_body(text: tk.Text, display: FindingDisplay, severity: str) -> None:
        """Render a FindingDisplay as a compiler diagnostic.

        An optional shared problem lead, then per frame a ``--> location`` line and the
        code framed by a ``|`` rail, with a caret line (``^^^ label``) built from literal
        spaces so it underlines the exact token, and finally a ``= hint:`` line.
        """
        if display.problem:
            text.insert(tk.END, display.problem + "\n", "problem")
        for fr in display.frames:
            text.insert(tk.END, f" --> {fr.location}\n", "floc")
            if fr.lines:
                text.insert(tk.END, "  |\n", "rail")
                for i, line in enumerate(fr.lines):
                    text.insert(tk.END, f"  |  {line}\n", "rail")
                    if fr.caret is not None and fr.caret[0] == i:
                        _, col, length = fr.caret
                        label = f" {fr.caret_label}" if fr.caret_label else ""
                        caret = " " * col + "^" * length + label
                        text.insert(tk.END, f"  |  {caret}\n", f"caret_{severity}")
                text.insert(tk.END, "  |\n", "rail")
        if display.hint:
            text.insert(tk.END, f"  = hint: {display.hint}\n", "hint")

    def _render(
        self,
        text: tk.Text,
        failing: list[tuple[str, str, str]],
        passing: list[tuple[str, str, str]],
        grouped: dict[str, list[FindingDisplay]],
    ) -> None:
        if failing:
            text.insert(tk.END, "FINDINGS\n", "section")
        for code, title, sev in failing:
            displays = grouped.get(code, [])
            _color, glyph = _SEVERITY_STYLE.get(sev, _SEVERITY_STYLE["warning"])
            rule_tag = f"rule_{sev}"
            self._ensure_rule_tag(text, rule_tag, sev)
            body = self._insert_section_header(
                text, code, f"{glyph}  {title}  · {len(displays)}", rule_tag
            )
            start = text.index("end-1c")

            for index, d in enumerate(displays):
                if index:
                    text.insert(tk.END, "\n")  # separate consecutive findings
                self._insert_body(text, d, sev)
            text.tag_add(body, start, "end-1c")

        if passing:
            text.insert(tk.END, "\n")
            body = self._insert_section_header(
                text, _PASSED_SECTION, f"PASSED ({len(passing)})", "section", default=False
            )
            start = text.index("end-1c")
            for _code, title, _sev in passing:
                text.insert(tk.END, _PASS_GLYPH + " ", "pass")
                text.insert(tk.END, title + "\n", "pass_muted")
            text.tag_add(body, start, "end-1c")

    def _restore_copy_button(self) -> None:
        self._copy_flash_after_id = None
        try:
            self._copy_btn.configure(text=_COPY_LABEL)
        except tk.TclError:  # window closed while the flash was pending
            pass

    def _copy_report(self) -> None:
        """Copy all findings, including bodies hidden by the Text's elide tags."""
        body = self._text.get("1.0", "end-1c").strip()
        report = f"Check Program - {self._summary_line}\n"
        if body:
            report += f"\n{body}\n"
        self.window.clipboard_clear()
        self.window.clipboard_append(report)

        if self._copy_flash_after_id is not None:
            try:
                self.window.after_cancel(self._copy_flash_after_id)
            except Exception:
                pass
        self._copy_btn.configure(text=_COPIED_LABEL)
        self._copy_flash_after_id = self.window.after(_COPY_FLASH_MS, self._restore_copy_button)

    def _show_data(self, data: AnalysisReportData) -> None:
        self._grouped = data.grouped_findings
        rows = _rule_rows(self._grouped)
        failing = [(c, t, s) for c, t, s in rows if self._grouped.get(c)]
        passing = [(c, t, s) for c, t, s in rows if not self._grouped.get(c)]
        total_findings = sum(self._count(c) for c, _, _ in failing)
        for child in self._summary.winfo_children():
            child.destroy()
        self._build_summary(self._summary, failing, passing, total_findings)
        self._source.configure(
            text=f"{data.project_name} - last saved ladder"
            if data.project_name
            else "Last saved ladder"
        )
        self._text.config(state=tk.NORMAL, cursor="arrow")
        self._text.delete("1.0", tk.END)
        for header, body, _expanded in self._sections.values():
            self._text.tag_delete(header, body)
        self._sections.clear()
        self._render(self._text, failing, passing, self._grouped)
        self._text.config(state=tk.DISABLED)
        self._active_section = None
        if self._sections:
            self._focus_section(next(iter(self._sections)))
        self._text.yview_moveto(0)

    def _finish_run_checks(self) -> None:
        self._run_after_id = None
        try:
            data = self._rerun() if self._rerun is not None else None
            if data is not None:
                self._show_data(data)
            else:
                self._source.configure(text="Checks were not refreshed; showing previous results.")
        except Exception as exc:
            self._source.configure(text="Checks failed; showing previous results.")
            messagebox.showerror("Analysis Error", f"Validation failed:\n{exc}", parent=self.window)
        finally:
            if self.window.winfo_exists():
                self._run_btn.configure(state=tk.NORMAL, text="Run Checks")

    def _run_checks(self) -> None:
        self._run_btn.configure(state=tk.DISABLED, text="Running checks...")
        self._run_after_id = self.window.after(1, self._finish_run_checks)

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self.window:
            for after_id in (self._copy_flash_after_id, self._run_after_id):
                if after_id is not None:
                    self.window.after_cancel(after_id)

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        data: AnalysisReportData,
        *,
        rerun: Callable[[], AnalysisReportData | None] | None = None,
        preferences: ProgramCheckPreferences | None = None,
    ) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Check Program")
        self.window.geometry("950x560")
        self.window.minsize(640, 360)
        self.window.transient(parent)
        self.window.bind("<Escape>", lambda _e: self.window.destroy())
        self.window.bind("<Destroy>", self._on_destroy)

        self._preferences = preferences if preferences is not None else ProgramCheckPreferences()
        self._rerun = rerun
        self._run_after_id: str | None = None
        self._sections: dict[str, tuple[str, str, bool]] = {}
        self._active_section: str | None = None
        self._grouped = data.grouped_findings
        self._summary_line = ""
        self._copy_flash_after_id: str | None = None

        main = ttk.Frame(self.window, padding=(12, 10))
        main.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(main)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        self._run_btn = ttk.Button(toolbar, text="Run Checks", command=self._run_checks)
        self._run_btn.pack(side=tk.LEFT, padx=(0, 12))
        if rerun is None:
            self._run_btn.configure(state=tk.DISABLED)
        self._source = ttk.Label(toolbar, foreground=_MUTED)
        self._source.pack(side=tk.LEFT)
        self._summary = ttk.Frame(main)
        self._summary.pack(fill=tk.X)
        ttk.Label(
            main,
            text="Click a check to expand or collapse it. Your choices are remembered.",
            foreground=_MUTED,
            wraplength=600,
        ).pack(anchor=tk.W, pady=(0, 6))

        # Packed against the bottom *before* the report body: the Text asks for
        # more height than the window has, and pack starves whatever comes last.
        buttons = ttk.Frame(main)
        buttons.pack(side=tk.BOTTOM, pady=(10, 0))
        self._copy_btn = ttk.Button(buttons, text=_COPY_LABEL, command=self._copy_report)
        self._copy_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Close", command=self.window.destroy).pack(side=tk.LEFT)
        self._preference_status = ttk.Label(main, foreground=_MUTED)
        self._preference_status.pack(side=tk.BOTTOM, anchor=tk.W)

        self._text = self._build_text(main)
        self._show_data(data)
