"""The annotation dialog builds its response fields from pyrung's table of physical kinds."""

from __future__ import annotations

import pytest
from pyrung.click.tag_map import TagMeta
from pyrung.core import PHYSICAL_KINDS

tk = pytest.importorskip("tkinter")

from clicknick.widgets.annotation_dialog import AnnotationDialog  # noqa: E402


@pytest.fixture(scope="module")
def tk_root():
    """One root for the whole module (per-test roots fail intermittently)."""
    # Creating a root after another module destroyed its own sometimes fails to find
    # init.tcl. A second try works, and only a real lack of a display should skip.
    for attempt in range(3):
        try:
            root = tk.Tk()
            break
        except tk.TclError as exc:  # pragma: no cover - depends on the machine
            if attempt == 2:
                pytest.skip(f"no Tk display available: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture()
def open_dialog(tk_root):
    dialogs: list[AnnotationDialog] = []

    def make(meta: TagMeta | None = None, **kwargs) -> AnnotationDialog:
        dialog = AnnotationDialog(tk_root, meta, "Feedback", None, **kwargs)
        dialogs.append(dialog)
        return dialog

    yield make
    for dialog in dialogs:
        if dialog.winfo_exists():
            dialog.destroy()


def _preview(dialog: AnnotationDialog) -> str:
    return dialog._preview_text.get("1.0", "end").strip()


def _fields(dialog: AnnotationDialog) -> list[str]:
    return [
        str(widget.cget("text"))
        for widget in dialog._response_frame.winfo_children()
        if int(widget.grid_info()["column"]) == 0
    ]


def _choose(dialog: AnnotationDialog, kind: str) -> None:
    dialog._kind_var.set(kind)
    dialog._on_kind_changed()


def test_the_kinds_on_offer_follow_the_tags_type(open_dialog):
    def offered(**kwargs) -> list[str]:
        return [kind.name for kind in open_dialog(**kwargs)._kinds]

    assert offered() == [kind.name for kind in PHYSICAL_KINDS]
    assert offered(feedback="bool") == ["delay", "flasher", "timed", "toggle"]
    assert offered(feedback="analog") == ["ramp", "approach"]
    # A comment's own kind stays on offer, so the dialog never hides what it holds.
    meta = TagMeta(link="Run", ramp_on="1")
    assert offered(meta=meta, feedback="bool") == ["delay", "flasher", "timed", "toggle", "ramp"]


def test_a_text_tag_shows_no_response_row(open_dialog):
    dialog = open_dialog(responds=False)
    assert dialog._kinds == ()
    assert not dialog._kind_row.winfo_manager()
    # A text tag whose comment already declares a response still shows it, so it can be cleared.
    held = open_dialog(TagMeta(link="Run", toggle=True), responds=False)
    assert [kind.name for kind in held._kinds] == ["toggle"]
    assert held._kind_row.winfo_manager() == "pack"


def test_a_field_tooltip_names_the_key():
    from pyrung.core import PHYSICAL_KEYS

    from clicknick.services.physical_response import key_tooltip

    tip = key_tooltip(PHYSICAL_KEYS["flasher_on"])
    assert tip.startswith(PHYSICAL_KEYS["flasher_on"].help)
    assert tip.endswith("Written in the comment as flasher_on.")


def test_a_comment_opens_on_its_kind_with_its_values(open_dialog):
    dialog = open_dialog(TagMeta(link="Bell", timed="500ms", maintained=True), feedback="bool")
    assert dialog._kind_var.get() == "timed"
    assert _fields(dialog) == ["On time:", "Maintained"]
    assert dialog._key_vars["timed"].get() == "500ms"
    assert dialog._key_vars["maintained"].get() is True
    assert _preview(dialog) == "[link=Bell, timed=500ms, maintained]"
    assert dialog._adv_visible


def test_each_kind_shows_its_own_keys_and_writes_only_those(open_dialog):
    dialog = open_dialog(TagMeta(link="Run", on_delay="1s"), feedback="bool")
    assert _fields(dialog) == ["On delay:", "Off delay:"]

    _choose(dialog, "flasher")
    assert _fields(dialog) == ["On time:", "Off time:"]
    dialog._key_vars["flasher_on"].set("8ms")
    dialog._key_vars["flasher_off"].set("9ms")
    assert _preview(dialog) == "[link=Run, flasher_on=8ms, flasher_off=9ms]"

    _choose(dialog, "toggle")
    assert _fields(dialog) == []
    assert _preview(dialog) == "[link=Run, toggle]"

    _choose(dialog, "")
    assert not dialog._response_frame.winfo_manager()
    assert _preview(dialog) == "[link=Run]"
    # The keys keep their values, so going back restores them.
    _choose(dialog, "delay")
    assert _preview(dialog) == "[link=Run, on_delay=1s]"


def test_a_bad_value_shows_in_the_preview_and_blocks_ok(open_dialog, monkeypatch):
    from clicknick.widgets import annotation_dialog

    errors: list[str] = []
    monkeypatch.setattr(
        annotation_dialog.messagebox, "showerror", lambda _title, text, **_kw: errors.append(text)
    )
    dialog = open_dialog(TagMeta(link="Run", ramp_on="1"), feedback="analog")
    dialog._key_vars["ramp_on"].set("fast")
    assert "ramp_on" in _preview(dialog)
    dialog._on_ok()
    assert errors == ["ramp_on: expected a number, got 'fast'"]
    assert dialog.winfo_exists()

    dialog._key_vars["ramp_on"].set("0.8")
    dialog._on_ok()
    assert dialog.result == TagMeta(link="Run", ramp_on="0.8")
