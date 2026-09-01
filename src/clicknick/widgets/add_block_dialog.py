import random
import re
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from pyclickplc.blocks import compose_structured_block_name

from .colors import BLOCK_COLOR_NAMES, BLOCK_COLORS
from .tooltip import bind_tooltip

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class AddBlockDialog(tk.Toplevel):
    """Dialog for adding a block with name, optional color, and optional structured kind."""

    def _select_color(self, color: str | None) -> None:
        """Select a color and update button states."""
        self._selected_color = color

        # Update button relief to show selection
        for c, btn in self._color_buttons.items():
            if c == color:
                btn.configure(relief="sunken")
            else:
                btn.configure(relief="raised")

    def _select_random_color(self) -> None:
        """Select a random color from the palette."""
        color_name = random.choice(BLOCK_COLOR_NAMES)
        self._select_color(color_name)

    # ── Name composition ──

    def _compose_name(self) -> str | None:
        base = self.name_var.get().strip().replace("<", "").replace(">", "").replace("/", "")
        if not base:
            return None
        kind = self._block_kind.get()
        try:
            if kind == "plain":
                return base
            if kind == "block":
                start_text = self._start_var.get().strip()
                if start_text:
                    start = int(start_text)
                    if start < 0:
                        return None
                    return compose_structured_block_name(base, "block", start=start)
                return compose_structured_block_name(base, "block")
            if kind == "named_array":
                count_text = self._count_var.get().strip()
                stride_text = self._stride_var.get().strip()
                if not count_text or not stride_text:
                    return None
                count = int(count_text)
                stride = int(stride_text)
                if count < 1 or stride < 1:
                    return None
                return compose_structured_block_name(
                    base, "named_array", count=count, stride=stride
                )
            if kind == "udt":
                field = self._field_var.get().strip()
                if not field:
                    return None
                return compose_structured_block_name(base, "udt", field=field)
        except (ValueError, TypeError):
            return None
        return None

    def _update_preview(self) -> None:
        name = self._compose_name()
        if name:
            self._preview_label.configure(text=f"Tag: {name}", foreground="black")
        elif self.name_var.get().strip():
            kind = self._block_kind.get()
            if kind == "plain":
                base = (
                    self.name_var.get().strip().replace("<", "").replace(">", "").replace("/", "")
                )
                self._preview_label.configure(text=f"Tag: {base}", foreground="black")
            else:
                self._preview_label.configure(text="(incomplete parameters)", foreground="gray")
        else:
            self._preview_label.configure(text="", foreground="gray")

    def _resize_to_fit(self) -> None:
        self.update_idletasks()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")

    # ── Advanced section ──

    def _toggle_advanced(self) -> None:
        self._adv_visible = not self._adv_visible
        if self._adv_visible:
            self._adv_frame.pack(fill=tk.X, pady=(0, 6), after=self._adv_toggle)
            self._adv_toggle.configure(text="Advanced ▼")
        else:
            self._adv_frame.pack_forget()
            self._adv_toggle.configure(text="Advanced ▶")
        self._resize_to_fit()

    def _on_kind_changed(self) -> None:
        for frame in (self._block_frame, self._array_frame, self._udt_frame):
            frame.pack_forget()
        kind = self._block_kind.get()
        if kind == "block":
            self._block_frame.pack(fill=tk.X, pady=(4, 0))
        elif kind == "named_array":
            self._array_frame.pack(fill=tk.X, pady=(4, 0))
        elif kind == "udt":
            self._udt_frame.pack(fill=tk.X, pady=(4, 0))
        self._update_preview()
        self._resize_to_fit()

    def _create_advanced_section(self, parent: ttk.Frame) -> None:
        self._adv_visible = False
        self._adv_toggle = ttk.Button(
            parent, text="Advanced ▶", command=self._toggle_advanced, width=12
        )
        self._adv_toggle.pack(anchor=tk.W, pady=(0, 2))

        self._adv_frame = ttk.LabelFrame(parent, text="Block Kind", padding=5)

        # Radio buttons
        radio_row = ttk.Frame(self._adv_frame)
        radio_row.pack(fill=tk.X)

        none_rb = ttk.Radiobutton(
            radio_row,
            text="None",
            variable=self._block_kind,
            value="plain",
            command=self._on_kind_changed,
        )
        none_rb.pack(side=tk.LEFT, padx=(0, 8))
        bind_tooltip(none_rb, "Grouping-only tag, no pyrung semantics")

        block_rb = ttk.Radiobutton(
            radio_row,
            text=":block",
            variable=self._block_kind,
            value="block",
            command=self._on_kind_changed,
        )
        block_rb.pack(side=tk.LEFT, padx=(0, 8))
        bind_tooltip(
            block_rb,
            "Semantic block for pyrung import.\nOptional start overrides the logical start address.",
        )

        array_rb = ttk.Radiobutton(
            radio_row,
            text=":named_array",
            variable=self._block_kind,
            value="named_array",
            command=self._on_kind_changed,
        )
        array_rb.pack(side=tk.LEFT, padx=(0, 8))
        bind_tooltip(
            array_rb,
            "Repeating array structure.\nRequires count (elements) and stride (addresses per element).",
        )

        udt_rb = ttk.Radiobutton(
            radio_row,
            text=":udt",
            variable=self._block_kind,
            value="udt",
            command=self._on_kind_changed,
        )
        udt_rb.pack(side=tk.LEFT)
        bind_tooltip(
            udt_rb,
            "One field of a user-defined type.\nMultiple Base.Field:udt blocks share the same base name.",
        )

        # Block start frame
        self._block_frame = ttk.Frame(self._adv_frame)
        ttk.Label(self._block_frame, text="start:").pack(side=tk.LEFT)
        self._start_var = tk.StringVar()
        self._start_var.trace_add("write", lambda *_: self._update_preview())
        start_entry = ttk.Entry(self._block_frame, textvariable=self._start_var, width=8)
        start_entry.pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(self._block_frame, text="(optional)", foreground="gray").pack(side=tk.LEFT)
        bind_tooltip(start_entry, "Logical start index (0-based). Leave blank for default.")

        # Named array frame
        self._array_frame = ttk.Frame(self._adv_frame)
        ttk.Label(self._array_frame, text="count:").pack(side=tk.LEFT)
        self._count_var = tk.StringVar()
        self._count_var.trace_add("write", lambda *_: self._update_preview())
        count_entry = ttk.Entry(self._array_frame, textvariable=self._count_var, width=6)
        count_entry.pack(side=tk.LEFT, padx=(4, 8))
        bind_tooltip(count_entry, "Number of array instances")

        ttk.Label(self._array_frame, text="stride:").pack(side=tk.LEFT)
        self._stride_var = tk.StringVar()
        self._stride_var.trace_add("write", lambda *_: self._update_preview())
        stride_entry = ttk.Entry(self._array_frame, textvariable=self._stride_var, width=6)
        stride_entry.pack(side=tk.LEFT, padx=(4, 4))
        bind_tooltip(stride_entry, "Number of addresses per instance")

        if self._row_count is not None:
            ttk.Label(
                self._array_frame,
                text=f"Selected: {self._row_count} rows",
                foreground="gray",
            ).pack(side=tk.LEFT, padx=(8, 0))

        # UDT field frame
        self._udt_frame = ttk.Frame(self._adv_frame)
        ttk.Label(self._udt_frame, text="field:").pack(side=tk.LEFT)
        self._field_var = tk.StringVar()
        self._field_var.trace_add("write", lambda *_: self._update_preview())
        field_entry = ttk.Entry(self._udt_frame, textvariable=self._field_var, width=20)
        field_entry.pack(side=tk.LEFT, padx=(4, 4))
        bind_tooltip(field_entry, "Field name within the UDT (e.g. Speed, Running)")
        ttk.Label(self._udt_frame, text="Result: Base.Field:udt", foreground="gray").pack(
            side=tk.LEFT
        )

    # ── OK / Cancel ──

    def _on_ok(self) -> None:
        """Handle OK button click."""
        base = self.name_var.get().strip().replace("<", "").replace(">", "").replace("/", "")

        if not base:
            messagebox.showerror("Error", "Please enter a block name.", parent=self)
            return

        kind = self._block_kind.get()

        if kind != "plain" and not _IDENT_RE.fullmatch(base):
            messagebox.showerror(
                "Invalid Name",
                "Block name must be a valid identifier "
                "(letters, digits, underscores; start with letter or underscore).",
                parent=self,
            )
            return

        if kind == "block":
            start_text = self._start_var.get().strip()
            if start_text:
                try:
                    start = int(start_text)
                    if start < 0:
                        raise ValueError
                except ValueError:
                    messagebox.showerror(
                        "Error", "Start must be a non-negative integer.", parent=self
                    )
                    return

        elif kind == "named_array":
            count_text = self._count_var.get().strip()
            stride_text = self._stride_var.get().strip()
            if not count_text or not stride_text:
                messagebox.showerror("Error", "Please enter both count and stride.", parent=self)
                return
            try:
                count = int(count_text)
                stride = int(stride_text)
                if count < 1 or stride < 1:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Error", "Count and stride must be positive integers.", parent=self
                )
                return

        elif kind == "udt":
            field = self._field_var.get().strip()
            if not field:
                messagebox.showerror("Error", "Please enter a field name.", parent=self)
                return
            if not _IDENT_RE.fullmatch(field):
                messagebox.showerror(
                    "Invalid Field Name",
                    "Field name must be a valid identifier.",
                    parent=self,
                )
                return

        name = self._compose_name()
        if name is None:
            messagebox.showerror("Error", "Could not compose block name.", parent=self)
            return

        if self._validate_name is not None:
            is_valid, error_msg = self._validate_name(name)
            if not is_valid:
                messagebox.showerror("Duplicate Block Name", error_msg, parent=self)
                return

        self.result = (name, self._selected_color)
        self.destroy()

    def _on_cancel(self) -> None:
        """Handle Cancel button click."""
        self.result = None
        self.destroy()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Block name entry
        ttk.Label(main_frame, text="Block Name:").pack(anchor=tk.W)
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", lambda *_: self._update_preview())
        self.name_entry = ttk.Entry(main_frame, textvariable=self.name_var, width=30)
        self.name_entry.pack(fill=tk.X, pady=(2, 10))

        # Color selection
        ttk.Label(main_frame, text="Background Color (optional):").pack(anchor=tk.W)

        # Color grid frame
        color_frame = ttk.Frame(main_frame)
        color_frame.pack(fill=tk.X, pady=(2, 5))

        # "None" button first
        none_btn = tk.Button(
            color_frame,
            text="None",
            width=6,
            relief="raised",
            command=lambda: self._select_color(None),
        )
        none_btn.grid(row=0, column=0, padx=1, pady=1)
        self._color_buttons[None] = none_btn

        # Color swatches in grid (6 per row)
        colors_per_row = 6
        for i, color_name in enumerate(BLOCK_COLOR_NAMES):
            row = (i // colors_per_row) + 1
            col = i % colors_per_row
            hex_color = BLOCK_COLORS[color_name]
            btn = tk.Button(
                color_frame,
                bg=hex_color,
                width=3,
                height=1,
                relief="raised",
                command=lambda cn=color_name: self._select_color(cn),
            )
            btn.grid(row=row, column=col, padx=1, pady=1)
            self._color_buttons[color_name] = btn

        # Random color button
        random_btn = ttk.Button(
            main_frame,
            text="\U0001f3b2 Random Color",
            command=self._select_random_color,
        )
        random_btn.pack(pady=(5, 10))

        self._select_random_color()

        # Preview label
        self._preview_label = ttk.Label(main_frame, text="", font=("Consolas", 9))
        self._preview_label.pack(anchor=tk.W, pady=(0, 6))

        # Advanced section
        self._create_advanced_section(main_frame)

        # Buttons frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(6, 0))

        ttk.Button(btn_frame, text="OK", command=self._on_ok, width=10).pack(
            side=tk.RIGHT, padx=(5, 0)
        )
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel, width=10).pack(side=tk.RIGHT)

    def __init__(
        self,
        parent: tk.Widget,
        validate_name: Callable[[str], tuple[bool, str]] | None = None,
        row_count: int | None = None,
    ):
        super().__init__(parent)
        self.title("Add Block")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()

        self.result: tuple[str, str | None] | None = None
        self._selected_color: str | None = None
        self._color_buttons: dict[str, tk.Button] = {}
        self._validate_name = validate_name
        self._row_count = row_count
        self._block_kind = tk.StringVar(value="plain")

        self._create_widgets()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # Focus on name entry
        self.name_entry.focus_set()

        # Bind Enter key to OK
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())
