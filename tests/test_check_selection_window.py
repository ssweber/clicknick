"""Save and Run chooses its settings destination from the active workspace."""

import pytest
from pyrung.core.validation.config import CheckConfig

from clicknick.services.program_check_selection import ProgramCheckSelection
from clicknick.views.check_selection_window import CheckSelectionWindow

tk = pytest.importorskip("tkinter")


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk display available: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def _widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from _widgets(child)


@pytest.mark.parametrize("has_workspace", [False, True])
def test_save_and_run_automatically_uses_the_active_settings(tk_root, tmp_path, has_workspace):
    appdata = tmp_path / "settings"
    defaults = ProgramCheckSelection(appdata=appdata)
    defaults.save(CheckConfig(select=("ALL",)))
    workspace = tmp_path / "workspace" if has_workspace else None
    selection = ProgramCheckSelection(workspace, appdata=appdata)
    if workspace is not None:
        selection.sync(workspace)
        selection.save(CheckConfig(select=("PTR",)))
    original = selection.load()
    saved = []
    dialog = CheckSelectionWindow(tk_root, selection, lambda: saved.append(True))
    dialog.window.withdraw()
    widgets = list(_widgets(dialog.window))
    buttons = {w.cget("text"): w for w in widgets if w.winfo_class() == "TButton"}
    labels = " ".join(w.cget("text") for w in widgets if w.winfo_class() == "TLabel")
    assert ("workspace's pyproject.toml" in labels) is has_workspace
    assert ("all programs without a workspace" in labels) is not has_workspace
    buttons["Select None"].invoke()
    assert selection.load() == original
    buttons["Save and Run"].invoke()
    assert saved == [True]
    assert selection.load() == CheckConfig(select=())
    assert defaults.load() == CheckConfig(select=("ALL",) if has_workspace else ())
    assert not dialog.window.winfo_exists()
