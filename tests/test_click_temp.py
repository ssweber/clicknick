"""The CLICK temp folder: one root, from Windows, for every caller."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from clicknick.live import session as live_session
from clicknick.utils.mdb_shared import find_click_database, find_fallback_csv

HWND = 0x00C40F12


def _click_folder(root: Path, hwnd: int = HWND) -> Path:
    folder = root / f"CLICK ({hwnd:08X})"
    (folder / "DataView").mkdir(parents=True)
    (folder / "SC_.mdb").write_bytes(b"")
    (folder / "Address.csv").write_text("", encoding="utf-8")
    return folder


@pytest.mark.skipif(sys.platform != "win32", reason="GetTempPathW is Windows only")
def test_the_folder_follows_the_windows_temp_path_not_the_user_name(monkeypatch, tmp_path):
    """A renamed account, a domain profile or a redirected TEMP: SC_.mdb is under %TMP%."""
    redirected = tmp_path / "jsmith.CORP" / "Temp"
    redirected.mkdir(parents=True)
    monkeypatch.setenv("TMP", str(redirected))
    monkeypatch.setenv("TEMP", str(redirected))
    monkeypatch.setenv("USERNAME", "renamed_account")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    folder = _click_folder(redirected)

    assert find_click_database(click_hwnd=HWND) == str(folder / "SC_.mdb")
    assert find_fallback_csv(HWND) == folder / "Address.csv"
    assert folder in live_session.iter_session_dirs()


def test_every_caller_uses_the_one_root(monkeypatch, tmp_path):
    from clicknick.data.cdv_file import click_dataview_folder
    from clicknick.utils import click_temp

    root = tmp_path / "D" / "Profiles" / "jsmith.CORP" / "Temp"
    root.mkdir(parents=True)
    monkeypatch.setattr(click_temp, "_windows_temp_path", lambda: str(root))
    folder = _click_folder(root)

    assert click_temp.click_temp_dir(HWND) == folder
    assert find_click_database(click_hwnd=HWND) == str(folder / "SC_.mdb")
    assert find_fallback_csv(HWND) == folder / "Address.csv"
    assert click_dataview_folder(HWND) == folder / "DataView"
    assert folder in live_session.iter_session_dirs()


def test_without_a_windows_temp_path_it_is_pythons_temp_folder(monkeypatch, tmp_path):
    from clicknick.utils import click_temp

    monkeypatch.setattr(click_temp, "_windows_temp_path", lambda: None)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    assert click_temp.temp_root() == tmp_path
    assert click_temp.click_temp_dir(0x1234) == tmp_path / "CLICK (00001234)"


def _short_path(path: Path) -> str:
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    return buffer.value if 0 < length < len(buffer) else str(path)


@pytest.mark.skipif(sys.platform != "win32", reason="8.3 names are Windows only")
def test_a_short_temp_path_is_given_in_its_long_form(monkeypatch, tmp_path):
    """A file dialog returns long paths: the DataView folder must compare equal to them."""
    from clicknick.data.cdv_file import click_dataview_folder
    from clicknick.utils import click_temp

    long_root = tmp_path / "Long Temp Folder Name"
    long_root.mkdir()
    short_root = _short_path(long_root)
    if Path(short_root).name == long_root.name:
        pytest.skip("this volume makes no 8.3 names")
    monkeypatch.setattr(click_temp, "_windows_temp_path", lambda: short_root)
    folder = _click_folder(long_root)

    assert click_temp.temp_root() == long_root
    assert click_dataview_folder(HWND) == folder / "DataView"
