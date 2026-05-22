"""Program analysis report window."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk

RULE_ORDER = [
    "CORE_STUCK_HIGH",
    "CORE_STUCK_LOW",
    "CORE_CONFLICTING_OUTPUT",
    "CORE_ANTITOGGLE",
    "CORE_READONLY_WRITE",
    "CORE_CHOICES_VIOLATION",
    "CORE_FINAL_MULTIPLE_WRITERS",
    "CORE_RANGE_VIOLATION",
    "CORE_MISSING_PROFILE",
    "CORE_POINTER_DEFAULT_BEFORE_BLOCK_START",
]

RULE_LABELS = {
    "CORE_STUCK_HIGH": "Stuck High (never reset)",
    "CORE_STUCK_LOW": "Stuck Low (never latched)",
    "CORE_CONFLICTING_OUTPUT": "Conflicting Output",
    "CORE_ANTITOGGLE": "Anti-Toggle Oscillation",
    "CORE_READONLY_WRITE": "Writes to Read-Only",
    "CORE_CHOICES_VIOLATION": "Choices Violation",
    "CORE_FINAL_MULTIPLE_WRITERS": "Final Tag — Multiple Writers",
    "CORE_RANGE_VIOLATION": "Range Violation",
    "CORE_MISSING_PROFILE": "Missing Physical Profile",
    "CORE_POINTER_DEFAULT_BEFORE_BLOCK_START": "Pointer Default Before Block",
}


@dataclass
class AnalysisReportData:
    """View model for the analysis report."""

    grouped_findings: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


class AnalysisReportWindow:
    def __init__(self, parent: tk.Tk | tk.Toplevel, data: AnalysisReportData) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Program Analysis Report")
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

        text.tag_configure("pass", foreground="#228B22")
        text.tag_configure("warning", foreground="#CC6600")
        text.tag_configure("finding", foreground="#333333", lmargin1=30, lmargin2=30)

        for code in RULE_ORDER:
            label = RULE_LABELS.get(code, code)
            findings = data.grouped_findings.get(code, [])

            if findings:
                text.insert(tk.END, f"⚠ {label} ({len(findings)})\n", "warning")
                for tag_name, message in findings:
                    text.insert(tk.END, f"{tag_name} — {message}\n", "finding")
            else:
                text.insert(tk.END, f"✓ {label}\n", "pass")

        text.config(state=tk.DISABLED)

        close_btn = ttk.Button(main_frame, text="Close", command=self.window.destroy)
        close_btn.pack(pady=(10, 0))
