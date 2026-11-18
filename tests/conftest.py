"""Shared fixtures."""

from __future__ import annotations

import itertools
import time
import tkinter as tk

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


@pytest.fixture(autouse=True)
def _own_settings_file(_settings_root, monkeypatch):
    """Give each test a settings.json of its own, away from the user's %LOCALAPPDATA%.

    The file does not exist until the test writes it.
    """
    from clicknick.services import settings_file

    path = _settings_root / str(next(_settings_paths)) / "settings.json"
    monkeypatch.setattr(settings_file, "default_settings_path", lambda: path)
