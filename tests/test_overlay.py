"""The overlay keeps its dropdown open when focus moves into it."""

from types import SimpleNamespace

import pytest

from clicknick.views.overlay import Overlay
from clicknick.widgets.nickname_combobox import ComboboxTCLManager, NicknameCombobox

tk = pytest.importorskip("tkinter")


@pytest.fixture
def tk_root(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk display available: {exc}")
    root.withdraw()
    # Each test gets a new interpreter, so the combobox Tcl overrides must be reinstalled.
    monkeypatch.setattr(ComboboxTCLManager, "_tcl_setup_done", False)
    yield root
    root.destroy()


@pytest.fixture
def overlay(tk_root):
    return Overlay(tk_root, SimpleNamespace(settings=None))


def _popdown_listbox(widget, combobox) -> str:
    """Create the Tk-owned dropdown for a combobox and return its listbox path."""
    return widget.tk.eval(f"ttk::combobox::PopdownWindow {combobox}") + ".f.l"


def _within_overlay_when_focus_on(overlay, path) -> bool:
    """Ask the overlay whether focus is inside it while Tk's ``focus`` reports ``path``."""
    real_tk = overlay.tk
    overlay.tk = SimpleNamespace(call=lambda *args: path)
    try:
        return overlay._focus_within_overlay()
    finally:
        overlay.tk = real_tk


def test_focus_on_dropdown_listbox_counts_as_inside_overlay(overlay):
    # tkinter has no widget for the dropdown, so focus_get() cannot identify it.
    listbox = _popdown_listbox(overlay, overlay.combobox)

    assert _within_overlay_when_focus_on(overlay, listbox)


def test_focus_on_overlay_widgets_counts_as_inside_overlay(overlay):
    for widget in (overlay, overlay.combobox, overlay.tooltip, overlay.tooltip.label):
        assert _within_overlay_when_focus_on(overlay, str(widget)), str(widget)


@pytest.mark.parametrize("suffix", ["", ".", "2", "2.child"])
def test_focus_elsewhere_counts_as_outside_overlay(overlay, suffix):
    # "" is no focus in this application; the rest are the root or a sibling window.
    path = f"{overlay}{suffix}" if suffix.startswith("2") else suffix

    assert not _within_overlay_when_focus_on(overlay, path)


@pytest.mark.parametrize(
    ("typed", "sent"),
    [
        ("c1", "C1"),
        ("X1", "X001"),
        ("xd0u", "XD0u"),
        ("ds100", "DS100"),
        ("Not_A_Nickname", "Not_A_Nickname"),
        ("100", "100"),
    ],
)
def test_typed_text_is_passed_on_in_click_address_form(tk_root, typed, sent):
    manager = SimpleNamespace(settings=None, get_address_for_nickname=lambda _, types=None: None)
    overlay = Overlay(tk_root, manager)
    inserted = []
    overlay._insert_text_to_field = inserted.append

    overlay._on_nickname_selected(typed)

    assert inserted == [sent]


def test_known_nickname_inserts_its_address(tk_root):
    manager = SimpleNamespace(settings=None, get_address_for_nickname=lambda _, types=None: "C5")
    overlay = Overlay(tk_root, manager)
    inserted = []
    overlay._insert_text_to_field = inserted.append

    overlay._on_nickname_selected("Motor_Run")

    assert inserted == ["C5"]


def test_programmatic_dropdown_returns_focus_to_combobox(tk_root):
    combobox = NicknameCombobox(tk_root, values=["Motor1_Run"])
    listbox = _popdown_listbox(tk_root, combobox)
    on_map = tk_root.tk.eval("bind ComboboxListbox <Map>").replace("%W", listbox)

    tk_root.tk.eval("set ttk::combobox::State(programmaticPost) 1")
    # Raises TclError if the script depends on a command this Tk version lacks.
    tk_root.tk.eval(on_map)

    assert tk_root.tk.eval("set ttk::combobox::State(programmaticPost)") == "0"


class _RecordingWin32:
    """Stands in for the Win32 helper and records what the overlay sends to CLICK."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args))

        return record


@pytest.fixture
def click_calls(monkeypatch):
    win32 = _RecordingWin32()
    monkeypatch.setattr("clicknick.views.overlay.WIN32", win32)
    return win32.calls


def _overlay_on_address_picker(tk_root, values=("Motor_Run", "Motor_Stop")):
    manager = SimpleNamespace(
        settings=None,
        get_address_for_nickname=lambda nickname, types=None: "C1" if nickname else None,
        get_filtered_nicknames=lambda types, text: list(values),
    )
    overlay = Overlay(tk_root, manager)
    overlay.target_window_id = 1
    overlay.target_window_class = "frmTagDB"
    overlay.target_edit_control = "Edit1"
    overlay.combobox.update_values(list(values))
    return overlay


def _escape_then_focus_out(overlay):
    overlay.combobox.event_handler._handle_keyrelease(SimpleNamespace(keysym="Escape", char=""))
    overlay._on_focus_out(None)


@pytest.mark.parametrize("typed", ["", "mot"])
def test_escape_sends_nothing_to_click(tk_root, click_calls, typed):
    overlay = _overlay_on_address_picker(tk_root)
    overlay.combobox.insert(0, typed)

    _escape_then_focus_out(overlay)

    assert click_calls == []


@pytest.mark.parametrize("typed", ["", "mot"])
def test_focus_out_sends_nothing_to_click(tk_root, click_calls, typed):
    overlay = _overlay_on_address_picker(tk_root)
    overlay.combobox.insert(0, typed)

    overlay._on_focus_out(None)

    assert click_calls == []


def test_enter_on_empty_text_sends_nothing_to_click(tk_root, click_calls):
    # CLICK's Address Picker accepts an Enter with empty text.
    overlay = _overlay_on_address_picker(tk_root, values=())

    overlay.combobox.finalize_entry()

    assert click_calls == []


def test_enter_on_a_nickname_still_sends_its_address_and_enter(tk_root, click_calls):
    overlay = _overlay_on_address_picker(tk_root)
    overlay.allowed_types = ["C"]
    overlay.combobox.insert(0, "Motor_Run")

    overlay.combobox.finalize_entry()

    names = [name for name, _ in click_calls]
    assert ("set_control_text", (1, "Edit1", "C1")) in click_calls
    assert names[-1] == "send_key"


def test_withdraw_after_a_focus_out_leaves_the_debounce_reset_pending(tk_root):
    # The monitor withdraws the overlay every 100 ms; the reset must still run,
    # or the overlay never shows for the same control again.
    overlay = _overlay_on_address_picker(tk_root)
    real_after = overlay.after
    scheduled = {}

    def record_after(ms, callback):
        after_id = real_after(100000, lambda: None)
        scheduled[after_id] = ms
        return after_id

    cancelled = []
    real_cancel = overlay.after_cancel
    overlay.after = record_after
    overlay.after_cancel = lambda after_id: (cancelled.append(after_id), real_cancel(after_id))

    overlay._on_focus_out(None)
    debounce_id = overlay.debounce_after_id
    overlay.withdraw()

    assert scheduled[debounce_id] == 1000
    assert debounce_id not in cancelled
    assert overlay.debounce_after_id == debounce_id


def _show_count(overlay, monkeypatch):
    shown = []
    monkeypatch.setattr(overlay, "position_near_edit_control", lambda: shown.append(1) or True)
    return shown


def test_escape_keeps_the_overlay_hidden_for_that_control(tk_root, click_calls, monkeypatch):
    overlay = _overlay_on_address_picker(tk_root)
    shown = _show_count(overlay, monkeypatch)

    _escape_then_focus_out(overlay)
    overlay._debounce_retrigger = False  # the 1 s debounce has expired
    overlay.show_combobox(["C"])

    assert shown == []


def test_escape_dismissal_ends_when_the_target_control_changes(tk_root, click_calls, monkeypatch):
    overlay = _overlay_on_address_picker(tk_root)
    shown = _show_count(overlay, monkeypatch)

    _escape_then_focus_out(overlay)
    overlay.set_target_window(1, "frmTagDB", "Edit2")
    overlay.show_combobox(["C"])

    assert shown == [1]


def test_focus_out_alone_lets_the_overlay_return_to_the_same_control(
    tk_root, click_calls, monkeypatch
):
    overlay = _overlay_on_address_picker(tk_root)
    shown = _show_count(overlay, monkeypatch)

    overlay._on_focus_out(None)
    overlay._debounce_retrigger = False
    overlay.show_combobox(["C"])

    assert shown == [1]
