"""Import from CSV never imports a field the file has no column for."""

from __future__ import annotations

from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from clicknick.widgets.import_csv_dialog import (  # noqa: E402
    COL_COMMENT,
    COL_FIRST_SCAN,
    COL_NICKNAME,
    NOT_IN_FILE,
    ImportCsvDialog,
    options_not_in_file,
)


@pytest.fixture(scope="module")
def tk_root():
    """One root for the whole module (per-test roots fail intermittently)."""
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


def _dialog_on(tk_root, path: Path) -> ImportCsvDialog:
    dialog = ImportCsvDialog(tk_root)
    dialog.csv_path = path
    dialog._load_csv()
    return dialog


def test_options_not_in_file():
    assert options_not_in_file(frozenset({"nickname"})) == {"comment", "first_scan"}
    assert options_not_in_file(frozenset({"nickname", "comment", "initial_value"})) == {
        "first_scan"
    }
    assert not options_not_in_file(frozenset({"nickname", "comment", "initial_value", "retentive"}))


def test_a_file_without_comments_does_not_import_them(tk_root, tmp_path):
    path = tmp_path / "names.csv"
    path.write_text("Address,Nickname\r\nC1,Motor\r\nC2,Pump\r\n", encoding="utf-8")
    dialog = _dialog_on(tk_root, path)
    try:
        row = dialog.sheet.get_row_data(0)
        assert row[COL_NICKNAME] == "Overwrite"
        assert (row[COL_COMMENT], row[COL_FIRST_SCAN]) == (NOT_IN_FILE, NOT_IN_FILE)

        dialog._on_import()

        _path, blocks, options = dialog.result
        assert options[id(blocks[0])] == {
            "nickname": "Overwrite",
            "comment": "Skip",
            "first_scan": "Skip",
        }
    finally:
        if dialog.winfo_exists():
            dialog.destroy()


def test_a_full_file_offers_every_option(tk_root, tmp_path):
    path = tmp_path / "full.csv"
    path.write_text(
        "Address,Data Type,Nickname,Initial Value,Retentive,Address Comment\r\n"
        'C1,BIT,"Motor",0,No,"Main motor"\r\n',
        encoding="utf-8",
    )
    dialog = _dialog_on(tk_root, path)
    try:
        dialog._on_import()

        _path, blocks, options = dialog.result
        assert options[id(blocks[0])] == {
            "nickname": "Overwrite",
            "comment": "Overwrite",
            "first_scan": "Merge",
        }
    finally:
        if dialog.winfo_exists():
            dialog.destroy()
