import gc

import pytest

from clicknick.views import dialogs


def test_build_system_info_includes_support_versions_and_driver(monkeypatch) -> None:
    monkeypatch.setattr(dialogs, "_installed_version", lambda _package: "0.12.0")

    info = dialogs._build_system_info("0.20.0", ["Microsoft Access Driver (*.mdb, *.accdb)"])

    assert "ClickNick: 0.20.0" in info
    assert "pyrung: 0.12.0" in info
    assert "MS Access ODBC: Microsoft Access Driver (*.mdb, *.accdb)" in info


def test_build_system_info_reports_missing_odbc_driver(monkeypatch) -> None:
    monkeypatch.setattr(dialogs, "_installed_version", lambda _package: "0.12.0")

    info = dialogs._build_system_info("0.20.0", [])

    assert "MS Access ODBC: Not installed" in info


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _with_root(tk, check) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"no Tk display available: {exc}")
    root.withdraw()
    try:
        check(root)
    finally:
        root.destroy()


def _copy_then_reset_after_close(root) -> None:
    from tkinter import ttk

    about = dialogs.AboutDialog(root, "0.20.0")
    scheduled = []
    about.window.after = lambda _delay, callback: scheduled.append(callback)
    (copy_button,) = [
        widget
        for widget in _descendants(about.window)
        if isinstance(widget, ttk.Button) and widget.cget("text") == "Copy System Info"
    ]
    copy_button.invoke()
    assert copy_button.cget("text") == "Copied"
    about.window.destroy()

    (reset,) = scheduled
    reset()  # This call used to raise TclError on the destroyed button.


def test_copied_label_reset_after_the_about_dialog_closed(monkeypatch) -> None:
    tk = pytest.importorskip("tkinter")
    monkeypatch.setattr(dialogs, "get_available_access_drivers", lambda: [])
    monkeypatch.setattr(dialogs.WIN32, "set_clipboard", lambda _text: None)
    try:
        _with_root(tk, _copy_then_reset_after_close)
    finally:
        # Free the root and the dialog's Tk objects on this thread. If they are freed later on
        # another test's worker thread, Tcl aborts the process.
        gc.collect()


def _csv_fallback_texts(root) -> None:
    from pathlib import Path
    from tkinter import ttk

    dialog = dialogs.CsvFallbackDialog(root, Path("Address.csv"))
    try:
        texts = [
            str(widget.cget("text"))
            for widget in _descendants(dialog.window)
            if isinstance(widget, ttk.Label | ttk.Button)
        ]
    finally:
        dialog.window.destroy()

    # Cancel goes on without nicknames (ConnectionController._connect_csv_fallback), so the
    # dialog must not say that a copy is needed to continue.
    assert not any("must save a copy" in text for text in texts)
    assert any("To go on without nicknames, click Cancel." in text for text in texts)
    assert "Cancel" in texts


def test_the_csv_fallback_dialog_says_that_cancel_goes_on_without_nicknames() -> None:
    tk = pytest.importorskip("tkinter")
    try:
        _with_root(tk, _csv_fallback_texts)
    finally:
        gc.collect()
