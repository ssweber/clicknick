"""Main-window menu actions: Export Workspace, Load Ladder CSV to Clipboard."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.connection_session import ClickConnection
from clicknick.services.analysis_service import AnalysisStatus


def _app(click: ClickConnection | None = None) -> ClickNickApp:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app.root = MagicMock()
    app._update_status = MagicMock()
    app._click = click
    app._session = None
    return app


@pytest.fixture
def dialogs(monkeypatch) -> SimpleNamespace:
    found = SimpleNamespace(
        showerror=MagicMock(),
        showinfo=MagicMock(),
        askdirectory=MagicMock(return_value=""),
        askopenfilename=MagicMock(return_value="C:/tmp/main.csv"),
    )
    for name in ("showerror", "showinfo"):
        monkeypatch.setattr(f"clicknick.app.messagebox.{name}", getattr(found, name))
    for name in ("askdirectory", "askopenfilename"):
        monkeypatch.setattr(f"clicknick.app.filedialog.{name}", getattr(found, name))
    return found


# -- Export Workspace after a failed build ------------------------------------------------------


def _failed_analysis(*, project_is_current: bool) -> SimpleNamespace:
    return SimpleNamespace(
        status=AnalysisStatus.FAILED,
        project_dir=Path("C:/tmp/pyrung_project"),
        project_is_current=project_is_current,
        error="ValueError: bad rung",
        export_project=MagicMock(return_value=3),
    )


def test_export_refuses_an_earlier_saves_workspace_after_a_failed_build(dialogs) -> None:
    app = _app(ClickConnection("1", 2, "Main.ckp"))
    analysis = _failed_analysis(project_is_current=False)
    app._session = SimpleNamespace(analysis=analysis)

    app._export_pyrung_project()

    (call,) = dialogs.showerror.call_args_list
    assert "could not be built from CLICK's last save" in call.args[1]
    assert "ValueError: bad rung" in call.args[1]
    dialogs.askdirectory.assert_not_called()
    analysis.export_project.assert_not_called()


def test_export_takes_the_workspace_a_failed_build_wrote(dialogs) -> None:
    app = _app(ClickConnection("1", 2, "Main.ckp"))
    analysis = _failed_analysis(project_is_current=True)
    app._session = SimpleNamespace(analysis=analysis)
    dialogs.askdirectory.return_value = "C:/tmp/out"

    app._export_pyrung_project()

    dialogs.showerror.assert_not_called()
    analysis.export_project.assert_called_once_with(Path("C:/tmp/out") / "pyrung_project")


# -- Load Ladder CSV to Clipboard goes to the connected window ----------------------------------


def test_load_ladder_csv_refuses_without_a_connected_window(dialogs, monkeypatch) -> None:
    copy = MagicMock()
    monkeypatch.setattr("clicknick.ladder.clipboard.copy_to_clipboard", copy)
    app = _app(None)

    app._load_ladder_csv()

    (call,) = dialogs.showinfo.call_args_list
    assert call.args[1].startswith("Not connected to CLICK.")
    dialogs.askopenfilename.assert_not_called()
    copy.assert_not_called()


def test_load_ladder_csv_copies_for_the_connected_window(dialogs, monkeypatch) -> None:
    versions, copies, loads = [], [], []
    monkeypatch.setattr(
        "clicknick.ladder.clipboard.is_click_v4", lambda hwnd: versions.append(hwnd) or True
    )
    monkeypatch.setattr(
        "clicknick.ladder.clipboard.copy_to_clipboard",
        lambda payload, owner_hwnd: copies.append((payload, owner_hwnd)),
    )
    monkeypatch.setattr(
        "clicknick.ladder.program.prepare_csv_load",
        lambda path, **kw: loads.append((path, kw)) or SimpleNamespace(payload=b"x", rung_count=2),
    )
    app = _app(ClickConnection("1", 0x2B, "Main.ckp"))
    app._live_mdb_path = MagicMock(return_value=Path("C:/tmp/SC_.mdb"))

    app._load_ladder_csv()

    assert versions == [0x2B]
    assert copies == [(b"x", 0x2B)]
    assert loads == [
        (Path("C:/tmp/main.csv"), {"click_v4": True, "mdb_path": Path("C:/tmp/SC_.mdb")})
    ]
    app._update_status.assert_called_once_with(
        "Copied 2 rungs from main.csv to clipboard", "connected"
    )
