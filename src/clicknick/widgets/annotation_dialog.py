"""Dialog for editing bracket-syntax tag annotations in comment fields."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from pyclickplc.validation import COMMENT_MAX_LENGTH
from pyrung.click.tag_map import TagMeta, format_tag_meta

from ..services.annotation_service import AnnotationService
from ..services.physical_response import (
    PHYSICAL_KEYS,
    FeedbackType,
    PhysicalKind,
    kinds_for,
    meta_fields,
    meta_response,
    physical_kind,
    response_kind,
    response_of,
    shown_keys,
)
from .tooltip import bind_tooltip as _bind_tooltip

#: The response radio that sets no response keys.
_NO_RESPONSE = ""


class AnnotationDialog(tk.Toplevel):
    """Dialog for structured editing of tag annotation metadata."""

    _BOOL_CHOICES: dict[int | float | str, str] = {0: "False", 1: "True"}

    # ── Info bar ──

    def _create_info_bar(self, parent: ttk.Frame) -> None:
        if self._block_tag_str:
            ttk.Label(parent, text=f"Block: {self._block_tag_str}", foreground="gray").pack(
                anchor=tk.W
            )
        if self._free_text:
            ttk.Label(parent, text=f"Comment: {self._free_text}", foreground="gray").pack(
                anchor=tk.W
            )
        if self._block_tag_str or self._free_text:
            ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(4, 8))

    # ── Parsing helpers ──

    @staticmethod
    def _parse_number(text: str) -> int | float | None:
        text = text.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_choices_input(raw: str) -> dict[int | float | str, str] | None:
        text = raw.strip()
        if not text:
            return None
        if text == "Bool":
            return dict(AnnotationDialog._BOOL_CHOICES)

        choices: dict[int | float | str, str] = {}
        for pair in text.split("|"):
            label, sep, value_text = pair.partition(":")
            label = label.strip()
            if not sep or not label:
                return None
            val_str = value_text.strip()
            try:
                val: int | float | str = int(val_str)
            except ValueError:
                try:
                    val = float(val_str)
                except ValueError:
                    val = val_str
            choices[val] = label
        return choices if choices else None

    @staticmethod
    def _format_choices_for_display(choices: dict[int | float | str, str]) -> str:
        if choices == AnnotationDialog._BOOL_CHOICES:
            return "Bool"
        return "|".join(f"{label}:{value}" for value, label in choices.items())

    def _response_kind(self) -> PhysicalKind | None:
        name = self._kind_var.get()
        return None if name == _NO_RESPONSE else physical_kind(name)

    # ── Build / populate ──

    def _build_meta_from_widgets(self) -> TagMeta | None:
        choices = None
        min_val: int | float | None = None
        max_val: int | float | None = None

        mode = self._constraint_mode.get()
        if mode == "choices":
            choices = self._parse_choices_input(self._choices_var.get())
        elif mode == "range":
            min_val = self._parse_number(self._min_var.get())
            max_val = self._parse_number(self._max_var.get())

        uom = self._uom_var.get().strip() or None

        physical = self._physical_var.get().strip() or None
        link = self._link_var.get().strip() or None

        values: dict[str, str | bool] = {}
        kind = self._response_kind()
        for key in kind.keys if kind is not None else ():
            if key.is_flag:
                # A required flag (toggle) is the kind itself.
                values[key.name] = key.required or bool(self._key_vars[key.name].get())
            else:
                values[key.name] = str(self._key_vars[key.name].get()).strip()

        system = self._system_var.get().strip() or None

        return TagMeta(
            readonly=self._readonly_var.get(),
            external=self._external_var.get(),
            final=self._final_var.get(),
            public=self._public_var.get(),
            lock=self._lock_var.get(),
            choices=choices,
            min=min_val,
            max=max_val,
            uom=uom,
            link=link,
            physical=physical,
            system=system,
            **meta_fields(response_of(values)),
        )

    def _update_preview(self) -> None:
        if self._updating:
            return
        meta = self._build_meta_from_widgets()
        if meta is None:
            return
        try:
            full_comment = AnnotationService.recompose_comment(
                self._block_tag_str, meta, self._free_text
            )
            bracket_text = format_tag_meta(meta) or "(no annotations)"
        except ValueError as exc:
            # A half-typed value, such as a time without units yet.
            full_comment = ""
            bracket_text = f"({exc})"

        self._preview_text.configure(state="normal")
        self._preview_text.delete("1.0", tk.END)
        self._preview_text.insert("1.0", bracket_text)
        self._preview_text.configure(state="disabled")
        if not full_comment:
            self._char_label.configure(text="")
            return

        length = len(full_comment)
        color = "red" if length > COMMENT_MAX_LENGTH else "gray"
        self._char_label.configure(text=f"{length} / {COMMENT_MAX_LENGTH} chars", foreground=color)

    def _on_flag_changed(self) -> None:
        readonly = self._readonly_var.get()
        self._final_cb.configure(state="disabled" if readonly else "normal")
        self._external_cb.configure(state="disabled" if readonly else "normal")
        if readonly:
            self._final_var.set(False)
            self._external_var.set(False)

        final = self._final_var.get()
        external = self._external_var.get()
        self._readonly_cb.configure(state="disabled" if (final or external) else "normal")
        if final or external:
            self._readonly_var.set(False)

        self._update_preview()

    # ── Flags section ──

    def _create_flags_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Flags", padding=5)
        frame.pack(fill=tk.X, pady=(0, 6))

        self._readonly_var = tk.BooleanVar()
        self._external_var = tk.BooleanVar()
        self._final_var = tk.BooleanVar()
        self._public_var = tk.BooleanVar()

        row = ttk.Frame(frame)
        row.pack(fill=tk.X)

        self._readonly_cb = ttk.Checkbutton(
            row, text="readonly", variable=self._readonly_var, command=self._on_flag_changed
        )
        self._readonly_cb.pack(side=tk.LEFT, padx=(0, 10))
        _bind_tooltip(self._readonly_cb, "Set via initial value, never written by the ladder")

        self._external_cb = ttk.Checkbutton(
            row, text="external", variable=self._external_var, command=self._on_flag_changed
        )
        self._external_cb.pack(side=tk.LEFT, padx=(0, 10))
        _bind_tooltip(
            self._external_cb, "Written by something outside the ladder (HMI, SCADA, comms)"
        )

        self._final_cb = ttk.Checkbutton(
            row, text="final", variable=self._final_var, command=self._on_flag_changed
        )
        self._final_cb.pack(side=tk.LEFT, padx=(0, 10))
        _bind_tooltip(self._final_cb, "Exactly one instruction in the program may write this tag")

        self._public_cb = ttk.Checkbutton(
            row, text="public", variable=self._public_var, command=self._on_flag_changed
        )
        self._public_cb.pack(side=tk.LEFT)
        _bind_tooltip(
            self._public_cb, "Part of the operator-facing interface, not internal plumbing"
        )

    def _on_constraint_mode_changed(self) -> None:
        mode = self._constraint_mode.get()
        if mode == "choices":
            self._choices_frame.pack(fill=tk.X, pady=(4, 0), before=self._uom_row)
            self._range_frame.pack_forget()
        elif mode == "range":
            self._choices_frame.pack_forget()
            self._range_frame.pack(fill=tk.X, pady=(4, 0), before=self._uom_row)
        else:
            self._choices_frame.pack_forget()
            self._range_frame.pack_forget()
        self._update_preview()

    # ── Value constraints section ──

    def _create_value_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Value Constraints", padding=5)
        frame.pack(fill=tk.X, pady=(0, 6))

        self._constraint_mode = tk.StringVar(value="none")

        radio_row = ttk.Frame(frame)
        radio_row.pack(fill=tk.X)
        ttk.Radiobutton(
            radio_row,
            text="None",
            variable=self._constraint_mode,
            value="none",
            command=self._on_constraint_mode_changed,
        ).pack(side=tk.LEFT, padx=(0, 10))
        choices_rb = ttk.Radiobutton(
            radio_row,
            text="Choices",
            variable=self._constraint_mode,
            value="choices",
            command=self._on_constraint_mode_changed,
        )
        choices_rb.pack(side=tk.LEFT, padx=(0, 10))
        _bind_tooltip(choices_rb, "Restrict valid values to a named set")
        range_rb = ttk.Radiobutton(
            radio_row,
            text="Min / Max",
            variable=self._constraint_mode,
            value="range",
            command=self._on_constraint_mode_changed,
        )
        range_rb.pack(side=tk.LEFT)
        _bind_tooltip(range_rb, "Declare the valid numeric range")

        self._choices_frame = ttk.Frame(frame)
        self._choices_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(self._choices_frame, text="Choices:").pack(side=tk.LEFT)
        self._choices_var = tk.StringVar()
        self._choices_var.trace_add("write", lambda *_: self._update_preview())
        ttk.Entry(self._choices_frame, textvariable=self._choices_var, width=35).pack(
            side=tk.LEFT, padx=(4, 0), fill=tk.X, expand=True
        )
        ttk.Label(self._choices_frame, text="Bool or Off:0|On:1", foreground="gray").pack(
            side=tk.LEFT, padx=(4, 0)
        )

        self._range_frame = ttk.Frame(frame)
        self._range_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(self._range_frame, text="Min:").pack(side=tk.LEFT)
        self._min_var = tk.StringVar()
        self._min_var.trace_add("write", lambda *_: self._update_preview())
        self._min_entry = ttk.Entry(self._range_frame, textvariable=self._min_var, width=8)
        self._min_entry.pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(self._range_frame, text="Max:").pack(side=tk.LEFT)
        self._max_var = tk.StringVar()
        self._max_var.trace_add("write", lambda *_: self._update_preview())
        self._max_entry = ttk.Entry(self._range_frame, textvariable=self._max_var, width=8)
        self._max_entry.pack(side=tk.LEFT, padx=(4, 0))

        self._uom_row = ttk.Frame(frame)
        self._uom_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(self._uom_row, text="Unit:").pack(side=tk.LEFT)
        self._uom_var = tk.StringVar()
        self._uom_var.trace_add("write", lambda *_: self._update_preview())
        uom_entry = ttk.Entry(self._uom_row, textvariable=self._uom_var, width=12)
        uom_entry.pack(side=tk.LEFT, padx=(4, 4))
        _bind_tooltip(uom_entry, "Unit of measurement label")
        ttk.Label(self._uom_row, text="e.g. degC, PSI, RPM", foreground="gray").pack(side=tk.LEFT)

        self._on_constraint_mode_changed()

    def _resize_to_fit(self) -> None:
        self.update_idletasks()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")

    def _toggle_advanced(self) -> None:
        self._adv_visible = not self._adv_visible
        if self._adv_visible:
            self._adv_frame.pack(fill=tk.X, pady=(0, 6), after=self._adv_toggle)
            self._adv_toggle.configure(text="Advanced ▼")
        else:
            self._adv_frame.pack_forget()
            self._adv_toggle.configure(text="Advanced ▶")
        self._resize_to_fit()

    def _on_physical_changed(self) -> None:
        self._update_preview()

    def _on_kind_changed(self) -> None:
        """Show the chosen kind's keys. Each key keeps its own value across kinds."""
        for child in self._response_frame.winfo_children():
            child.destroy()
        kind = self._response_kind()
        for row, key in enumerate(shown_keys(kind) if kind is not None else ()):
            var = self._key_vars[key.name]
            if key.is_flag:
                check = ttk.Checkbutton(
                    self._response_frame, text=key.name, variable=var, command=self._update_preview
                )
                check.grid(row=row, column=0, columnspan=3, sticky=tk.W)
                _bind_tooltip(check, key.help)
                continue
            label = ttk.Label(self._response_frame, text=f"{key.name}:")
            label.grid(row=row, column=0, sticky=tk.W)
            entry = ttk.Entry(self._response_frame, textvariable=var, width=12)
            entry.grid(row=row, column=1, sticky=tk.W, padx=(4, 4), pady=1)
            hint = ttk.Label(self._response_frame, text=key.unit, foreground="gray")
            hint.grid(row=row, column=2, sticky=tk.W)
            for widget in (label, entry, hint):
                _bind_tooltip(widget, key.help)
        if kind is None:
            self._response_frame.pack_forget()
        else:
            self._response_frame.pack(fill=tk.X, pady=(0, 2), before=self._sys_row)
        self._update_preview()

    # ── Advanced section ──

    def _create_advanced_section(self, parent: ttk.Frame) -> None:
        self._adv_visible = False
        self._adv_toggle = ttk.Button(
            parent, text="Advanced ▶", command=self._toggle_advanced, width=12
        )
        self._adv_toggle.pack(anchor=tk.W, pady=(0, 2))

        self._adv_frame = ttk.LabelFrame(parent, text="Advanced", padding=5)

        # ── Physical ──
        ttk.Label(self._adv_frame, text="Physical", font=("", 9, "bold")).pack(anchor=tk.W)

        name_row = ttk.Frame(self._adv_frame)
        name_row.pack(fill=tk.X, pady=(2, 2))
        ttk.Label(name_row, text="name:").pack(side=tk.LEFT)
        self._physical_var = tk.StringVar()
        self._physical_var.trace_add("write", lambda *_: self._on_physical_changed())
        self._physical_entry = ttk.Entry(name_row, textvariable=self._physical_var, width=20)
        self._physical_entry.pack(side=tk.LEFT, padx=(4, 0))
        _bind_tooltip(
            self._physical_entry,
            "Name of the physical device this feedback represents.\n"
            "Optional: left empty, it is named after this tag. Give several\n"
            "tags the same name to share one definition.\n"
            "Pick a response below for how the device answers its link.",
        )

        # The response kinds come from pyrung's table, each with its own keys.
        kind_row = ttk.Frame(self._adv_frame)
        kind_row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(kind_row, text="response:").pack(side=tk.LEFT)
        self._kind_var = tk.StringVar(value=_NO_RESPONSE)
        ttk.Radiobutton(
            kind_row,
            text="None",
            variable=self._kind_var,
            value=_NO_RESPONSE,
            command=self._on_kind_changed,
        ).pack(side=tk.LEFT, padx=(4, 8))
        for kind in self._kinds:
            radio = ttk.Radiobutton(
                kind_row,
                text=kind.label,
                variable=self._kind_var,
                value=kind.name,
                command=self._on_kind_changed,
            )
            radio.pack(side=tk.LEFT, padx=(0, 8))
            _bind_tooltip(radio, kind.description)

        self._key_vars: dict[str, tk.Variable] = {}
        for name, key in PHYSICAL_KEYS.items():
            var: tk.Variable = tk.BooleanVar() if key.is_flag else tk.StringVar()
            if not key.is_flag:
                var.trace_add("write", lambda *_: self._update_preview())
            self._key_vars[name] = var
        self._response_frame = ttk.Frame(self._adv_frame)

        self._sys_row = ttk.Frame(self._adv_frame)
        self._sys_row.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(self._sys_row, text="system:").pack(side=tk.LEFT)
        self._system_var = tk.StringVar()
        self._system_var.trace_add("write", lambda *_: self._update_preview())
        sys_entry = ttk.Entry(self._sys_row, textvariable=self._system_var, width=20)
        sys_entry.pack(side=tk.LEFT, padx=(4, 0))
        _bind_tooltip(sys_entry, "Group related physical devices together")

        link_row = ttk.Frame(self._adv_frame)
        link_row.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(link_row, text="link:").pack(side=tk.LEFT)
        self._link_var = tk.StringVar()
        self._link_var.trace_add("write", lambda *_: self._update_preview())
        ttk.Entry(link_row, textvariable=self._link_var, width=20).pack(side=tk.LEFT, padx=(4, 4))
        link_hint = ttk.Label(
            link_row, text="e.g. Motor_Run, ~Y001 or State:RUNNING", foreground="gray"
        )
        link_hint.pack(side=tk.LEFT)
        _bind_tooltip(
            link_hint,
            "Tag or CLICK address that drives this feedback signal,\n"
            "with an optional :value trigger.\n"
            "~ in front of a bit drives it while the bit is OFF",
        )

        # ── Lock ──
        ttk.Separator(self._adv_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        self._lock_var = tk.BooleanVar()
        lock_cb = ttk.Checkbutton(
            self._adv_frame,
            text="lock",
            variable=self._lock_var,
            command=self._update_preview,
        )
        lock_cb.pack(anchor=tk.W)
        _bind_tooltip(lock_cb, "Include in behavioral change tracking between program versions")

        self._on_kind_changed()

    # ── Preview ──

    def _create_preview(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Preview", padding=5)
        frame.pack(fill=tk.X, pady=(0, 6))

        self._preview_text = tk.Text(frame, height=2, wrap=tk.WORD, state="disabled")
        self._preview_text.pack(fill=tk.X)

        self._char_label = ttk.Label(frame, text="", foreground="gray")
        self._char_label.pack(anchor=tk.E)

    # ── OK / Cancel ──

    def _on_ok(self) -> None:
        meta = self._build_meta_from_widgets()
        if meta is None:
            return

        errors = AnnotationService.validate_meta(meta)
        if errors:
            messagebox.showerror("Validation Error", "\n".join(errors), parent=self)
            return

        full_comment = AnnotationService.recompose_comment(
            self._block_tag_str, meta, self._free_text
        )
        if len(full_comment) > COMMENT_MAX_LENGTH:
            proceed = messagebox.askyesno(
                "Comment Too Long",
                f"The comment is {len(full_comment)} characters "
                f"(limit: {COMMENT_MAX_LENGTH}).\n\nSave anyway?",
                parent=self,
            )
            if not proceed:
                return

        self.result = meta
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()

    # ── Buttons ──

    def _create_buttons(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X)
        ttk.Button(frame, text="OK", command=self._on_ok, width=10).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(frame, text="Cancel", command=self._on_cancel, width=10).pack(side=tk.RIGHT)

    def _create_widgets(self) -> None:
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        self._create_info_bar(main)
        self._create_flags_section(main)
        self._create_value_section(main)
        self._create_advanced_section(main)
        self._create_preview(main)
        self._create_buttons(main)

    def _populate_from_meta(self, meta: TagMeta) -> None:
        self._updating = True
        try:
            self._readonly_var.set(meta.readonly)
            self._external_var.set(meta.external)
            self._final_var.set(meta.final)
            self._public_var.set(meta.public)
            self._on_flag_changed()

            self._lock_var.set(meta.lock)
            self._link_var.set(meta.link or "")
            self._physical_var.set(meta.physical or "")
            for name, value in meta_response(meta):
                self._key_vars[name].set(value)
            self._system_var.set(meta.system or "")

            if meta.choices is not None:
                self._constraint_mode.set("choices")
                self._choices_var.set(self._format_choices_for_display(meta.choices))
            elif meta.min is not None or meta.max is not None:
                self._constraint_mode.set("range")
                self._min_var.set(str(meta.min) if meta.min is not None else "")
                self._max_var.set(str(meta.max) if meta.max is not None else "")
            else:
                self._constraint_mode.set("none")
            self._on_constraint_mode_changed()

            self._uom_var.set(meta.uom or "")

            kind = response_kind(meta_response(meta))
            self._kind_var.set(_NO_RESPONSE if kind is None else kind.name)
            self._on_kind_changed()
            self._on_physical_changed()

            if AnnotationService.meta_has_advanced(meta):
                if not self._adv_visible:
                    self._toggle_advanced()
        finally:
            self._updating = False

        self._update_preview()

    def __init__(
        self,
        parent: tk.Widget,
        current_meta: TagMeta | None,
        free_text: str,
        block_tag_str: str | None,
        *,
        feedback: FeedbackType | None = None,
    ):
        """*feedback* offers only the bool or the analog response kinds (``None``: all)."""
        super().__init__(parent)
        self.title("Edit Annotations")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()

        self.result: TagMeta | None = None
        self._free_text = free_text
        self._block_tag_str = block_tag_str
        self._meta = current_meta or TagMeta()
        # The comment's own kind stays on offer, even when it doesn't suit the tag's type.
        current_kind = response_kind(meta_response(self._meta))
        self._kinds = tuple(
            kind for kind in kinds_for(None) if kind in kinds_for(feedback) or kind == current_kind
        )
        self._updating = True

        self._create_widgets()
        self._updating = False
        self._populate_from_meta(self._meta)

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        self.bind("<Return>", lambda _: self._on_ok())
        self.bind("<Escape>", lambda _: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
