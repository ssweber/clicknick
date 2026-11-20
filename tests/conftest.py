"""Shared fixtures."""

from __future__ import annotations

import itertools
import os
import time
import tkinter as tk
from pathlib import Path

import pytest

_settings_paths = itertools.count()


def _new_root() -> tk.Tk:
    """Create a Tk root. Try again if Tk fails to read init.tcl while other test processes start."""
    for attempt in range(5):
        try:
            return tk.Tk()
        except tk.TclError:
            if attempt == 4:
                raise
            time.sleep(1)
    raise AssertionError("unreachable")


@pytest.fixture(scope="module")
def tk_root():
    """One hidden Tk root per module, for tests that do not make their own.

    Modules that create their own roots destroy them. A root that outlives its module
    breaks the next module's. A machine with no display fails these tests. It does not
    skip them.
    """
    root = _new_root()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


@pytest.fixture(scope="session")
def _settings_root(tmp_path_factory):
    return tmp_path_factory.mktemp("settings")


def _real_clicknick_files() -> dict[str, tuple[int, int]]:
    """Return the size and mtime of every file under the real %LOCALAPPDATA%/ClickNick."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return {}
    root = Path(local_app_data) / "ClickNick"
    files = {}
    for path in root.rglob("*"):
        # A running ClickNick writes live/ and compare/ itself.
        if path.relative_to(root).parts[0] in ("live", "compare"):
            continue
        try:
            if path.is_file():
                stat = path.stat()
                files[str(path)] = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            continue
    return files


@pytest.fixture(scope="session", autouse=True)
def _real_local_app_data_is_untouched():
    """Fail the run if a test created, changed or deleted a file under the real ClickNick folder.

    The snapshot is taken before any fixture changes LOCALAPPDATA. It leaves out live/ and
    compare/, which a running ClickNick writes.
    """
    before = _real_clicknick_files()
    yield
    after = _real_clicknick_files()
    changed = sorted(
        path for path in before.keys() | after.keys() if before.get(path) != after.get(path)
    )
    if changed:
        pytest.fail(
            "Tests touched the real %LOCALAPPDATA%/ClickNick folder: "
            + ", ".join(changed)
            + ". A ClickNick that is running can change these files too. "
            "If it was open, rerun the tests.",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _own_local_app_data(_settings_root, monkeypatch):
    """Point LOCALAPPDATA and APPDATA at a folder of the test's own.

    ClickNick keeps its settings, workspace index, simulator state, snapshots and popup
    flags under %LOCALAPPDATA%/ClickNick. Nothing is created until the test writes it.
    """
    from clicknick.live import session as live_session

    root = _settings_root / str(next(_settings_paths))
    root.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    monkeypatch.setenv("APPDATA", str(root))
    monkeypatch.setattr(live_session, "_LOCALAPPDATA", root)
