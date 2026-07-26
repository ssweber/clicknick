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
from dataclasses import dataclass, field
from tkinter import ttk
from typing import TYPE_CHECKING

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
_COPY_LABEL = "Copy Report"
_COPIED_LABEL = "Copied"
_COPY_FLASH_MS = 1200


@dataclass
class AnalysisReportData:
    """View model for the analysis report: rule code -> its FindingDisplays."""

    grouped_findings: dict[str, list[FindingDisplay]] = field(default_factory=dict)


def _rule_rows(grouped: dict[str, list[FindingDisplay]]) -> list[tuple[str, str, str]]:
    """`(code, title, severity)` rows in display order, straight from the registry.

    Registry rules come first in canonical (severity-desc) order; any finding
    whose code the installed pyrung doesn't know is appended — never dropped —
    with the raw code as its title and warning styling.
    """
    from pyrung.core.validation import ordered_rules

    specs = ordered_rules()
    known = {s.code for s in specs}
    rows = [(s.code, s.title, s.severity) for s in specs]
    rows += [(code, code, "warning") for code in sorted(grouped) if code not in known]
    return rows


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
        return text

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
            text.insert(tk.END, f"{glyph}  {title}  · {len(displays)}\n", rule_tag)

            for index, d in enumerate(displays):
                if index:
                    text.insert(tk.END, "\n")  # separate consecutive findings
                self._insert_body(text, d, sev)

        if passing:
            text.insert(tk.END, f"\nPASSED ({len(passing)})\n", "section")
            for _code, title, _sev in passing:
                text.insert(tk.END, _PASS_GLYPH + " ", "pass")
                text.insert(tk.END, title + "\n", "pass_muted")

    def _restore_copy_button(self) -> None:
        self._copy_flash_after_id = None
        try:
            self._copy_btn.configure(text=_COPY_LABEL)
        except tk.TclError:  # window closed while the flash was pending
            pass

    def _copy_report(self) -> None:
        """Copy the report as plain text: summary line, then the rendered body."""
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

    def __init__(self, parent: tk.Tk | tk.Toplevel, data: AnalysisReportData) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Check Program")
        self.window.geometry("950x560")
        self.window.minsize(640, 360)
        self.window.transient(parent)
        self.window.bind("<Escape>", lambda _e: self.window.destroy())

        self._grouped = data.grouped_findings
        self._summary_line = ""
        self._copy_flash_after_id: str | None = None
        rows = _rule_rows(data.grouped_findings)
        failing = [(c, t, s) for c, t, s in rows if data.grouped_findings.get(c)]
        passing = [(c, t, s) for c, t, s in rows if not data.grouped_findings.get(c)]
        total_findings = sum(len(data.grouped_findings.get(c, [])) for c, _, _ in failing)

        main = ttk.Frame(self.window, padding=(12, 10))
        main.pack(fill=tk.BOTH, expand=True)

        self._build_summary(main, failing, passing, total_findings)

        # Packed against the bottom *before* the report body: the Text asks for
        # more height than the window has, and pack starves whatever comes last.
        buttons = ttk.Frame(main)
        buttons.pack(side=tk.BOTTOM, pady=(10, 0))
        self._copy_btn = ttk.Button(buttons, text=_COPY_LABEL, command=self._copy_report)
        self._copy_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(buttons, text="Close", command=self.window.destroy).pack(side=tk.LEFT)

        self._text = self._build_text(main)
        self._render(self._text, failing, passing, data.grouped_findings)
        self._text.config(state=tk.DISABLED)
