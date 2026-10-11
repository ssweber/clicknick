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


def test_programmatic_dropdown_returns_focus_to_combobox(tk_root):
    combobox = NicknameCombobox(tk_root, values=["Motor1_Run"])
    listbox = _popdown_listbox(tk_root, combobox)
    on_map = tk_root.tk.eval("bind ComboboxListbox <Map>").replace("%W", listbox)

    tk_root.tk.eval("set ttk::combobox::State(programmaticPost) 1")
    # Raises TclError if the script depends on a command this Tk version lacks.
    tk_root.tk.eval(on_map)

    assert tk_root.tk.eval("set ttk::combobox::State(programmaticPost)") == "0"
