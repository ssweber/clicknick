import tkinter as tk


class CharLimitTooltip:
    def _on_sheet_destroy(self, event):
        """Ensure no timers are left hanging when the UI is closed."""
        if self.hide_timer:
            self.sheet.after_cancel(self.hide_timer)
            self.hide_timer = None

    def _ensure_tooltip_exists(self, limit):
        if self.tip_label is None and self.sheet.winfo_exists():
            self.tip_label = tk.Label(
                self.sheet,
                bg="#ffffe0",
                fg="#333333",
                relief="solid",
                borderwidth=1,
                font=("Arial", 8),
                padx=3,
                pady=1,
            )

    def _destroy_tooltip(self):
        if self.hide_timer:
            try:
                self.sheet.after_cancel(self.hide_timer)
            except:
                pass
            self.hide_timer = None
        if self.tip_label:
            try:
                self.tip_label.destroy()
            except:
                pass
            self.tip_label = None

    def _update_visuals(self, editor, limit):
        try:
            if not self.tip_label or not editor.winfo_exists():
                return

            if isinstance(editor, tk.Text):
                text = editor.get("1.0", "end-1c")
            else:
                text = editor.get()
            curr_len = len(text)

            self.tip_label.config(text=f"{curr_len}/{limit}")
            if curr_len > limit:
                self.tip_label.config(fg="white", bg="#d9534f")
            else:
                self.tip_label.config(fg="#333333", bg="#ffffe0")

            cursor_pos = editor.bbox("insert")
            if cursor_pos:
                cx, cy, cw, ch = cursor_pos
                screen_x = editor.winfo_rootx() + cx
                screen_y = editor.winfo_rooty() + cy + ch
                rel_x = screen_x - self.sheet.winfo_rootx()
                rel_y = screen_y - self.sheet.winfo_rooty()

                self.tip_label.place(x=rel_x + 10, y=rel_y + 15, anchor="nw")
                self.tip_label.lift()
        except Exception:
            self._destroy_tooltip()

    def _on_key_release(self, editor, limit):
        if self.hide_timer:
            self.sheet.after_cancel(self.hide_timer)

        # Check if widget still exists before scheduling
        if self.sheet.winfo_exists():
            self.hide_timer = self.sheet.after(self.hide_delay, self._destroy_tooltip)

        self._ensure_tooltip_exists(limit)
        self._update_visuals(editor, limit)

    def _setup_tracking(self, limit):
        # Safety check: if sheet was destroyed in those 20ms
        if not self.sheet.winfo_exists():
            return

        editor = self.sheet.focus_get()
        if not isinstance(editor, (tk.Entry, tk.Text)):
            return

        editor.bind("<KeyRelease>", lambda e: self._on_key_release(editor, limit))
        self._on_key_release(editor, limit)

    def _on_edit_begin(self, event):
        if not event:
            return
        self._destroy_tooltip()
        c = event.column
        if c in self.char_limits:
            limit = self.char_limits[c]
            # Use 'after' on the sheet so it's tracked by the widget lifecycle
            self.sheet.after(20, lambda: self._setup_tracking(limit))
        return event.value if event.value is not None else ""

    def __init__(self, sheet, char_limits, hide_delay=1000):
        self.sheet = sheet
        self.char_limits = char_limits
        self.hide_delay = hide_delay

        self.tip_label = None
        self.hide_timer = None

        # 1. Bind to sheet events
        self.sheet.extra_bindings("begin_edit_cell", self._on_edit_begin)

        # 2. SELF-CLEANUP: If the sheet is destroyed, stop all timers immediately
        self.sheet.bind("<Destroy>", self._on_sheet_destroy, add="+")
