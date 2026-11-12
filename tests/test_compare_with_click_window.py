"""Comparing with another CLICK window: a copy of its last save, shown in Preview Changes."""

from __future__ import annotations

import typing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from laddercodec import Coil, Contact, Rung, read_csv
from laddercodec.model import Program

from clicknick.app import ClickNickApp
from clicknick.connection_session import ClickConnection
from clicknick.data.data_source import CsvDataSource
from clicknick.models.address_row import AddressRow
from clicknick.services.click_snapshot import (
    remove_stale_snapshots,
    snapshot_click_program,
    snapshot_dir,
)

_IT = typing.get_type_hints(Contact)["type"]


def _rung(coil: str) -> Rung:
    return Rung(
        logical_rows=1,
        conditions=[["-"] * 31],
        instructions=[Coil(_IT.COIL_OUT, coil)],
        comment=None,
    )


@pytest.fixture
def click_dir(tmp_path: Path, monkeypatch) -> Path:
    """Another CLICK window's temp folder: main and the subroutine "Motor", and its database."""
    folder = tmp_path / "CLICK (000A1B2C)"
    folder.mkdir()
    programs = {
        b"Scr1.tmp": Program("Main Program", 1, [_rung("C1")]),
        b"Scr2.tmp": Program("Motor", 2, [_rung("C10"), _rung("C11")]),
    }
    for name in programs:
        (folder / name.decode()).write_bytes(name)
    (folder / "SC_.mdb").write_bytes(b"")
    monkeypatch.setattr("clicknick.ladder.program.decode_program", programs.__getitem__)
    rows = {1: AddressRow("X", 1, nickname="Start_PB")}

    class _Connection:
        def __init__(self, _path: str) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            pass

    monkeypatch.setattr("clicknick.utils.mdb_operations.MdbConnection", _Connection)
    monkeypatch.setattr("clicknick.utils.mdb_operations.load_all_addresses", lambda _conn: rows)
    return folder


def test_a_copy_holds_the_windows_programs_and_nicknames(click_dir: Path, tmp_path: Path) -> None:
    dest = tmp_path / "copy"

    snapshot_click_program(click_dir, dest)

    assert len(read_csv(dest / "main.csv")) == 1
    assert len(read_csv(dest / "subroutines" / "motor.csv")) == 2
    rows = CsvDataSource(str(dest / "nicknames.csv")).load_all_addresses()
    assert [row.nickname for row in rows.values()] == ["Start_PB"]


def test_taking_the_copy_again_replaces_it_whole(click_dir: Path, tmp_path: Path) -> None:
    dest = tmp_path / "copy"
    (dest / "subroutines").mkdir(parents=True)
    (dest / "subroutines" / "deleted_since.csv").write_text("old", encoding="utf-8")

    snapshot_click_program(click_dir, dest)

    assert not (dest / "subroutines" / "deleted_since.csv").exists()


def test_a_window_with_nothing_saved_leaves_the_last_copy(tmp_path: Path) -> None:
    empty = tmp_path / "CLICK (000A1B2C)"
    empty.mkdir()
    dest = tmp_path / "copy"
    dest.mkdir()
    (dest / "main.csv").write_text("last copy", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        snapshot_click_program(empty, dest)

    assert (dest / "main.csv").read_text(encoding="utf-8") == "last copy"
    assert [path.name for path in tmp_path.iterdir()] == sorted(["CLICK (000A1B2C)", "copy"])


def test_each_click_window_has_its_own_copy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert snapshot_dir(0xA1B2C) == tmp_path / "ClickNick" / "compare" / "CLICK (000A1B2C)"


def test_a_database_that_cannot_be_read_leaves_only_the_nicknames_out(
    click_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    def _locked(_path: str):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("clicknick.utils.mdb_operations.MdbConnection", _locked)
    dest = tmp_path / "copy"

    note = snapshot_click_program(click_dir, dest)

    assert note == "its nicknames were left out: database is locked"
    assert (dest / "main.csv").exists()
    assert not (dest / "nicknames.csv").exists()


def test_a_copy_that_cannot_be_swapped_in_leaves_the_last_one_whole(
    click_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    dest = tmp_path / "copy"
    dest.mkdir()
    (dest / "main.csv").write_text("last copy", encoding="utf-8")
    replace = Path.replace

    def _held_open(self: Path, target):
        if self.name == "copy" and self.parent != tmp_path:  # The new copy, into place
            raise PermissionError("[WinError 32] in use")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", _held_open)

    with pytest.raises(PermissionError):
        snapshot_click_program(click_dir, dest)

    assert (dest / "main.csv").read_text(encoding="utf-8") == "last copy"


def test_stale_snapshots_are_removed_except_those_kept(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for hwnd in (1, 2, 3):
        (snapshot_dir(hwnd) / "csv").mkdir(parents=True)
    compare = snapshot_dir(1).parent
    (compare / ".CLICK (00000003)-k2j8").mkdir()  # Left by a copy cut short
    (compare / "notes").mkdir()

    removed = remove_stale_snapshots([1], [snapshot_dir(2)])

    assert sorted(path.name for path in removed) == [".CLICK (00000003)-k2j8", "CLICK (00000003)"]
    assert sorted(path.name for path in compare.iterdir()) == [
        "CLICK (00000001)",
        "CLICK (00000002)",
        "notes",
    ]


def test_no_compare_folder_removes_nothing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert remove_stale_snapshots([], []) == []


def _app(windows: dict[int, str] | None = None) -> ClickNickApp:
    """An app connected to the CLICK window 1; *windows* are the open ones, hwnd -> file."""
    windows = {1: "Line1.ckp", 2: "Line2.ckp"} if windows is None else windows
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app._update_status = MagicMock()
    app.root = MagicMock()
    app._click = SimpleNamespace(hwnd=1)
    app.detector = SimpleNamespace(
        get_click_instances=lambda: [
            SimpleNamespace(hwnd=hwnd, filename=filename) for hwnd, filename in windows.items()
        ]
    )
    app._show_preview_changes = MagicMock()
    return app


def test_the_menu_lists_the_other_click_windows() -> None:
    app = _app()
    app._compare_with_click_window = MagicMock()
    menu = MagicMock()

    app._fill_other_click_menu(menu)

    (call,) = menu.add_command.call_args_list
    assert call.kwargs["label"] == "Line2.ckp"
    call.kwargs["command"]()
    app._compare_with_click_window.assert_called_once_with(2, "Line2.ckp")


def test_without_a_connection_the_menu_lists_every_click_window() -> None:
    app = _app()
    app._click = None
    menu = MagicMock()

    app._fill_other_click_menu(menu)

    assert [c.kwargs["label"] for c in menu.add_command.call_args_list] == [
        "Line1.ckp",
        "Line2.ckp",
    ]


def _copies(monkeypatch, note: str = "") -> list[tuple[str, Path]]:
    """Record each copy taken instead of reading a CLICK window."""
    copies: list[tuple[str, Path]] = []

    def _copy(click_dir: Path, dest: Path) -> str:
        copies.append((click_dir.name, dest))
        return note

    monkeypatch.setattr("clicknick.services.click_snapshot.snapshot_click_program", _copy)
    return copies


def test_comparing_with_a_click_window_shows_its_copy_as_another_plc(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    copies = _copies(monkeypatch)
    app = _app()

    app._compare_with_click_window(2, "Line2.ckp")

    assert copies == [("CLICK (00000002)", snapshot_dir(2))]
    (call,) = app._show_preview_changes.call_args_list
    assert call.args == (snapshot_dir(2),)
    source = call.kwargs["source"]
    assert (source.label, source.takes_nicknames, source.deletes_only_in_click) == (
        "Line2",
        False,
        False,
    )
    call.kwargs["refresh_source"]()  # Refresh: copied again, and shown again
    assert len(copies) == 2
    app.root.configure.assert_called_with(cursor="")  # Not left busy


def test_refresh_refuses_a_click_window_that_has_another_project_open(monkeypatch) -> None:
    copies = _copies(monkeypatch)
    showerror = MagicMock()
    monkeypatch.setattr("clicknick.app.messagebox.showerror", showerror)
    windows = {1: "Line1.ckp", 2: "Line2.ckp"}
    app = _app(windows)
    app._compare_with_click_window(2, "Line2.ckp")
    refresh = app._show_preview_changes.call_args.kwargs["refresh_source"]

    windows[2] = "Unrelated.ckp"
    refresh()

    assert len(copies) == 1  # Not copied over with another project
    assert "has another project open now" in showerror.call_args.args[1]


def test_nicknames_left_out_are_said_in_the_status(monkeypatch) -> None:
    _copies(monkeypatch, note="its nicknames were left out: database is locked")
    app = _app()

    app._compare_with_click_window(2, "Line2.ckp")

    app._update_status.assert_called_with(
        "Compared with Line2.ckp; its nicknames were left out: database is locked", "error"
    )
    app._show_preview_changes.assert_called_once()


def test_a_click_window_with_nothing_saved_is_explained(monkeypatch) -> None:
    def _nothing(_click_dir, _dest):
        raise FileNotFoundError("No Scr*.tmp files found")

    monkeypatch.setattr("clicknick.services.click_snapshot.snapshot_click_program", _nothing)
    showerror = MagicMock()
    monkeypatch.setattr("clicknick.app.messagebox.showerror", showerror)
    app = _app()

    app._compare_with_click_window(2, "Line2.ckp")

    assert "Line2.ckp has no saved program" in showerror.call_args.args[1]
    app._show_preview_changes.assert_not_called()


def test_refreshing_the_window_list_removes_copies_of_closed_windows(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for hwnd in (1, 2, 3, 4, 5):
        (snapshot_dir(hwnd) / "csv").mkdir(parents=True)
    compare = snapshot_dir(1).parent
    (compare / ".CLICK (00000003)-k2j8").mkdir()  # Left by a copy cut short
    (compare / "notes.txt").write_text("mine", encoding="utf-8")
    app = _app()  # Windows 1 and 2 are open
    app._click = ClickConnection("p1", 1, "Line1.ckp")
    app.click_instances = []
    app.instances_combobox = {}
    app.selected_instance_var = MagicMock()
    app.start_button = MagicMock()
    app._data = None
    shown = SimpleNamespace(winfo_exists=lambda: True)
    closed = SimpleNamespace(winfo_exists=lambda: False)
    app._preview_changes_windows = {
        snapshot_dir(4).resolve(): shown,
        snapshot_dir(5).resolve(): closed,
    }

    app.refresh_click_instances()

    assert sorted(path.name for path in compare.iterdir()) == [
        "CLICK (00000001)",
        "CLICK (00000002)",
        "CLICK (00000004)",
        "notes.txt",
    ]
