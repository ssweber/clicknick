"""Shared fixtures."""

from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture(scope="module")
def tk_root():
    """One hidden Tk root per module, for tests that do not make their own.

    Modules that create their own roots destroy them, and a root that outlives its
    module breaks the next module's. A machine with no display fails these tests;
    it does not skip them.
    """
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass
