"""Add Block dialog: the tooltips state pyrung's rules for a block's start."""

from __future__ import annotations

import gc

import pytest
from pyrung.click.tag_map._parsers import _default_logical_block_start

from clicknick.widgets import add_block_dialog


def test_the_start_tooltip_states_pyrungs_default_start(tk_root, monkeypatch) -> None:
    tooltips: list[str] = []
    monkeypatch.setattr(
        add_block_dialog, "bind_tooltip", lambda _widget, text: tooltips.append(text)
    )
    dialog = add_block_dialog.AddBlockDialog(tk_root)
    dialog.destroy()
    gc.collect()

    # pyrung starts a block at 1, or at 0 when the block's first address is numbered 0.
    assert _default_logical_block_start((1, 2, 3)) == 1
    assert _default_logical_block_start((0, 1, 2)) == 0
    (start,) = [text for text in tooltips if text.startswith("The index of the first element")]
    assert "Leave it blank to start at 1,\nor at 0 if the first address" in start
    assert not any("0-based" in text for text in tooltips)


@pytest.fixture(autouse=True)
def _no_grab(monkeypatch) -> None:
    # The dialog grabs the pointer and keyboard. A test has no use for the grab.
    monkeypatch.setattr(add_block_dialog.AddBlockDialog, "grab_set", lambda _self: None)
