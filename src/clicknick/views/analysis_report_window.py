"""Program analysis report window.

Rule identity, order, titles, and severity are owned by pyrung's validation
registry — this window reads them at render time (``ordered_rules()``) instead of
keeping its own copy.  Add or rename a rule in pyrung and it shows up here
automatically; the only display knowledge clicknick owns is the severity palette.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk

# Severity -> text colour.  Severities come from pyrung's registry.
_SEVERITY_COLOR = {
    "error": "#B22222",
    "warning": "#CC6600",
    "info": "#1E6FB8",
    "advisory": "#777777",
}
_PASS_COLOR = "#228B22"


@dataclass
class AnalysisReportData:
    """View model for the analysis report."""

    grouped_findings: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


def _rule_rows(grouped: dict[str, list[tuple[str, str]]]) -> list[tuple[str, str, str]]:
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
    def __init__(self, parent: tk.Tk | tk.Toplevel, data: AnalysisReportData) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Program Check")
        self.window.geometry("700x500")
        self.window.minsize(500, 300)
        self.window.transient(parent)

        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        total_findings = sum(len(v) for v in data.grouped_findings.values())
        rules_with_findings = sum(1 for v in data.grouped_findings.values() if v)

        if total_findings == 0:
            summary = "All checks passed — no findings."
        else:
            summary = f"{total_findings} finding(s) across {rules_with_findings} rule(s)"

        ttk.Label(main_frame, text=summary, font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 10))

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            padx=10,
            pady=10,
            cursor="arrow",
        )
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text.tag_configure("pass", foreground=_PASS_COLOR)
        text.tag_configure("finding", foreground="#333333", lmargin1=30, lmargin2=30)
        for severity, color in _SEVERITY_COLOR.items():
            text.tag_configure(severity, foreground=color)

        for code, title, severity in _rule_rows(data.grouped_findings):
            findings = data.grouped_findings.get(code, [])
            style = severity if severity in _SEVERITY_COLOR else "warning"
            if findings:
                text.insert(tk.END, f"⚠ {title} ({len(findings)})\n", style)
                for tag_name, message in findings:
                    text.insert(tk.END, f"{tag_name} — {message}\n", "finding")
            else:
                text.insert(tk.END, f"✓ {title}\n", "pass")

        text.config(state=tk.DISABLED)

        close_btn = ttk.Button(main_frame, text="Close", command=self.window.destroy)
        close_btn.pack(pady=(10, 0))
