"""Shared loader and lifetime cache for the main-window action icons."""

from __future__ import annotations

import base64
import tkinter as tk
from collections.abc import Callable
from importlib.resources import files

ACTION_ICON_FILES = {
    "address_editor": "address_editor.png",
    "data_view": "data_view.png",
    "check_program": "check_program.png",
    "console": "console.png",
    "rung_apply": "rung_apply.png",
    "reload_from_click": "reload_from_click.png",
}


class ActionIconCache:
    """Load each action icon once and retain the Tk image for the app lifetime."""

    def __init__(
        self,
        master: tk.Misc,
        image_factory: Callable[..., tk.PhotoImage] = tk.PhotoImage,
    ) -> None:
        self._master = master
        self._image_factory = image_factory
        self._images: dict[str, tk.PhotoImage] = {}

    def get(self, name: str) -> tk.PhotoImage:
        """Return the named image, loading its packaged PNG on first use."""
        if name not in self._images:
            filename = ACTION_ICON_FILES[name]
            resource = files("clicknick.resources").joinpath("action_icons", filename)
            encoded = base64.b64encode(resource.read_bytes()).decode("ascii")
            self._images[name] = self._image_factory(master=self._master, data=encoded)
        return self._images[name]
