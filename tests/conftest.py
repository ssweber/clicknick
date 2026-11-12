"""Shared fixtures."""

from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_root():
    """One hidden Tk root for every test that builds widgets and does not make its own.

    A machine with no display fails these tests; it does not skip them.
    """
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass
