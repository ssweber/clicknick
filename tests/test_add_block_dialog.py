"""Add Block dialog: the tooltips state pyrung's rules for a block's start."""

from __future__ import annotations

import gc

import pytest

from clicknick.widgets import add_block_dialog


def test_the_start_tooltip_states_pyrungs_default_start(tk_root, monkeypatch) -> None:
    tooltips: list[str] = []
    monkeypatch.setattr(
        add_block_dialog, "bind_tooltip", lambda _widget, text: tooltips.append(text)
    )
    dialog = add_block_dialog.AddBlockDialog(tk_root)
    dialog.destroy()
    gc.collect()

    (start,) = [text for text in tooltips if text.startswith("The index of the first element")]
    assert "Leave it blank to start at 1,\nor at 0 if the first address" in start
    assert not any("0-based" in text for text in tooltips)


@pytest.mark.parametrize(
    ("first", "last", "start"),
    [("DS1", "DS3", 1), ("XD0", "XD2", 0)],
    ids=["numbered from 1", "numbered from 0"],
)
def test_pyrung_starts_a_block_as_the_start_tooltip_says(tmp_path, first, last, start) -> None:
    """The tooltip's default start is the start that pyrung gives a block with no start."""
    from pyclickplc.blocks import compose_structured_block_name
    from pyrung.click import TagMap

    name = compose_structured_block_name("Fill", "block")
    header = "Address,Data Type,Nickname,Initial Value,Retentive,Address Comment"
    data_type = "HEX" if first.startswith("XD") else "INT"
    rows = [f'{first},{data_type},"",,No,"<{name}>"', f'{last},{data_type},"",,No,"</{name}>"']
    nicknames = tmp_path / "nicknames.csv"
    nicknames.write_text("\n".join([header, *rows, ""]), encoding="utf-8")

    (entry,) = TagMap.from_nickname_file(nicknames).blocks()
    assert entry.logical.start == start


@pytest.fixture(autouse=True)
def _no_grab(monkeypatch) -> None:
    # The dialog grabs the pointer and keyboard. A test has no use for the grab.
    monkeypatch.setattr(add_block_dialog.AddBlockDialog, "grab_set", lambda _self: None)
