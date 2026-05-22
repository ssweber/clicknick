"""Dialog for editing bracket-syntax tag annotations in comment fields."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from pyclickplc.validation import COMMENT_MAX_LENGTH
from pyrung.click.tag_map import TagMeta, format_tag_meta

from ..services.annotation_service import AnnotationService

_DURATION_HINT = "e.g. 50ms, 2s, 1s500ms"


class AnnotationDialog(tk.Toplevel):
    """Dialog for structured editing of tag annotation metadata."""

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
        from pyrung.click.tag_map._parsers import _BOOL_CHOICE_PRESET, _CHOICE_PRESETS

        text = raw.strip()
        if not text:
            return None
        if text in _CHOICE_PRESETS:
            return dict(_BOOL_CHOICE_PRESET)

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
        from pyrung.click.tag_map._parsers import _BOOL_CHOICE_PRESET

        if choices == _BOOL_CHOICE_PRESET:
            return "Bool"
        return "|".join(f"{label}:{value}" for value, label in choices.items())

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

        on_delay: str | None = None
        off_delay: str | None = None
        profile: str | None = None
        if physical:
            if self._phys_mode.get() == "timing":
                on_delay = self._on_delay_var.get().strip() or None
                off_delay = self._off_delay_var.get().strip() or None
            else:
                profile = self._profile_var.get().strip() or None

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
            on_delay=on_delay,
            off_delay=off_delay,
            profile=profile,
            system=system,
        )

    def _update_preview(self) -> None:
        if self._updating:
            return
        meta = self._build_meta_from_widgets()
        if meta is None:
            return
        full_comment = AnnotationService.recompose_comment(
            self._block_tag_str, meta, self._free_text
        )
        bracket_text = format_tag_meta(meta)

        self._preview_text.configure(state="normal")
        self._preview_text.delete("1.0", tk.END)
        self._preview_text.insert("1.0", bracket_text if bracket_text else "(no annotations)")
        self._preview_text.configure(state="disabled")

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

        self._external_cb = ttk.Checkbutton(
            row, text="external", variable=self._external_var, command=self._on_flag_changed
        )
        self._external_cb.pack(side=tk.LEFT, padx=(0, 10))

        self._final_cb = ttk.Checkbutton(
            row, text="final", variable=self._final_var, command=self._on_flag_changed
        )
        self._final_cb.pack(side=tk.LEFT, padx=(0, 10))

        self._public_cb = ttk.Checkbutton(
            row, text="public", variable=self._public_var, command=self._on_flag_changed
        )
        self._public_cb.pack(side=tk.LEFT)

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
        ttk.Radiobutton(
            radio_row,
            text="Choices",
            variable=self._constraint_mode,
            value="choices",
            command=self._on_constraint_mode_changed,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(
            radio_row,
            text="Min / Max",
            variable=self._constraint_mode,
            value="range",
            command=self._on_constraint_mode_changed,
        ).pack(side=tk.LEFT)

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
        ttk.Entry(self._uom_row, textvariable=self._uom_var, width=12).pack(
            side=tk.LEFT, padx=(4, 4)
        )
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
        has_physical = bool(self._physical_var.get().strip())
        state = "normal" if has_physical else "disabled"
        self._on_delay_entry.configure(state=state)
        self._off_delay_entry.configure(state=state)
        for child in self._profile_frame.winfo_children():
            if isinstance(child, ttk.Entry):
                child.configure(state=state)
        self._update_preview()

    def _on_phys_mode_changed(self) -> None:
        if self._phys_mode.get() == "timing":
            self._timing_frame.pack(fill=tk.X, pady=(0, 2), before=self._sys_row)
            self._profile_frame.pack_forget()
        else:
            self._timing_frame.pack_forget()
            self._profile_frame.pack(fill=tk.X, pady=(0, 2), before=self._sys_row)
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

        type_row = ttk.Frame(self._adv_frame)
        type_row.pack(fill=tk.X, pady=(0, 2))
        self._phys_mode = tk.StringVar(value="timing")
        ttk.Label(type_row, text="type:").pack(side=tk.LEFT)
        ttk.Radiobutton(
            type_row,
            text="Timing",
            variable=self._phys_mode,
            value="timing",
            command=self._on_phys_mode_changed,
        ).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Radiobutton(
            type_row,
            text="Profile",
            variable=self._phys_mode,
            value="profile",
            command=self._on_phys_mode_changed,
        ).pack(side=tk.LEFT)

        self._timing_frame = ttk.Frame(self._adv_frame)
        self._timing_frame.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(self._timing_frame, text="on_delay:").pack(side=tk.LEFT)
        self._on_delay_var = tk.StringVar()
        self._on_delay_var.trace_add("write", lambda *_: self._update_preview())
        self._on_delay_entry = ttk.Entry(
            self._timing_frame, textvariable=self._on_delay_var, width=10
        )
        self._on_delay_entry.pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(self._timing_frame, text="off_delay:").pack(side=tk.LEFT)
        self._off_delay_var = tk.StringVar()
        self._off_delay_var.trace_add("write", lambda *_: self._update_preview())
        self._off_delay_entry = ttk.Entry(
            self._timing_frame, textvariable=self._off_delay_var, width=10
        )
        self._off_delay_entry.pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(self._timing_frame, text=_DURATION_HINT, foreground="gray").pack(side=tk.LEFT)

        self._profile_frame = ttk.Frame(self._adv_frame)
        ttk.Label(self._profile_frame, text="profile:").pack(side=tk.LEFT)
        self._profile_var = tk.StringVar()
        self._profile_var.trace_add("write", lambda *_: self._update_preview())
        ttk.Entry(self._profile_frame, textvariable=self._profile_var, width=20).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        self._sys_row = ttk.Frame(self._adv_frame)
        self._sys_row.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(self._sys_row, text="system:").pack(side=tk.LEFT)
        self._system_var = tk.StringVar()
        self._system_var.trace_add("write", lambda *_: self._update_preview())
        ttk.Entry(self._sys_row, textvariable=self._system_var, width=20).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        link_row = ttk.Frame(self._adv_frame)
        link_row.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(link_row, text="link:").pack(side=tk.LEFT)
        self._link_var = tk.StringVar()
        self._link_var.trace_add("write", lambda *_: self._update_preview())
        ttk.Entry(link_row, textvariable=self._link_var, width=20).pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(link_row, text="e.g. EnableField or State:RUNNING", foreground="gray").pack(
            side=tk.LEFT
        )

        # ── Lock ──
        ttk.Separator(self._adv_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        self._lock_var = tk.BooleanVar()
        ttk.Checkbutton(
            self._adv_frame,
            text="lock",
            variable=self._lock_var,
            command=self._update_preview,
        ).pack(anchor=tk.W)

        self._on_phys_mode_changed()

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
            self._on_delay_var.set(meta.on_delay or "")
            self._off_delay_var.set(meta.off_delay or "")
            self._profile_var.set(meta.profile or "")
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

            if meta.profile is not None:
                self._phys_mode.set("profile")
            else:
                self._phys_mode.set("timing")
            self._on_phys_mode_changed()
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
    ):
        super().__init__(parent)
        self.title("Edit Annotations")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()

        self.result: TagMeta | None = None
        self._free_text = free_text
        self._block_tag_str = block_tag_str
        self._meta = current_meta or TagMeta()
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
