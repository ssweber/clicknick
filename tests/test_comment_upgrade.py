"""Upgrade Project rewrites old annotation forms with pyrung's migrations, staged for review."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.models.address_row import AddressRow
from clicknick.services.annotation_service import AnnotationService
from clicknick.services.comment_upgrade_service import (
    find_comment_upgrades,
    stage_comment_upgrades,
)

ENCODER = "[link=Run, profile=pulse:on_dwell=8ms|off_dwell=8ms] Encoder"
LEVEL = "<Tank:block> [profile=ramp:up=0.8|down=-0.05, link=Fill] Level"
STUCK = "[link=Heat, profile=approach:toward=180] Oven"


class MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def __init__(self, rows):
        self.rows = rows

    def load_all_addresses(self):
        return self.rows

    def save_changes(self, rows):
        return len(rows)


def _store(comments: dict[tuple[str, int], str]) -> AddressStore:
    rows = {
        get_addr_key(bank, address): AddressRow(
            memory_type=bank, address=address, nickname=f"Tag_{bank}{address}", comment=comment
        )
        for (bank, address), comment in comments.items()
    }
    store = AddressStore(MockDataSource(rows))
    store.load_initial_data()
    return store


def _comment(store: AddressStore, bank: str, address: int) -> str:
    row = store.get_visible_row(get_addr_key(bank, address))
    assert row is not None
    return row.comment


def test_pyrung_refuses_an_old_form_and_names_the_upgrade():
    with pytest.raises(ValueError, match="Upgrade project"):
        AnnotationService.decompose_comment(ENCODER)


def test_finding_upgrades_changes_nothing():
    store = _store({("X", 1): ENCODER, ("X", 2): "[link=Run, on_delay=1s] Aux", ("X", 3): ""})
    (upgrade,) = find_comment_upgrades(store)
    assert upgrade.display_address == "X001"
    assert upgrade.replacement == "[link=Run, flasher_on=8ms, flasher_off=8ms] Encoder"
    assert upgrade.unresolved == ()
    assert not store.has_unsaved_changes()


def test_every_upgrade_is_staged_in_one_edit_session():
    store = _store({("X", 1): ENCODER, ("DF", 1): LEVEL, ("X", 2): "Plain [note]"})
    upgrades = stage_comment_upgrades(store)

    assert len(upgrades) == 2
    assert _comment(store, "X", 1) == "[link=Run, flasher_on=8ms, flasher_off=8ms] Encoder"
    assert _comment(store, "DF", 1) == (
        "<Tank:block> [ramp_on=0.8, ramp_off=-0.05, link=Fill] Level"
    )
    assert _comment(store, "X", 2) == "Plain [note]"
    # One undo takes every upgrade back.
    assert store.get_undo_description() == "Upgrade project annotations"
    store.undo()
    assert _comment(store, "X", 1) == ENCODER
    assert _comment(store, "DF", 1) == LEVEL
    # Each upgraded comment reads in the current form.
    store.redo()
    for bank, address in (("X", 1), ("DF", 1)):
        AnnotationService.decompose_comment(_comment(store, bank, address))


def test_a_form_no_migration_reads_is_reported_not_staged():
    store = _store({("DF", 2): STUCK})
    (upgrade,) = stage_comment_upgrades(store)
    assert not upgrade.changed
    assert upgrade.unresolved == ("profile=approach:toward=180",)
    assert not store.has_unsaved_changes()


def test_cli_upgrade_project_stages_and_opens_changed():
    store = _store({("X", 1): ENCODER, ("DF", 2): STUCK})
    opened: list[str] = []

    result = dispatch(
        DispatchContext(store=store, show_address_editor=opened.append), "tag upgrade-project"
    )

    assert result.splitlines()[:4] == [
        "OK: 1 comment upgrade staged",
        f"X001: {ENCODER!r} -> '[link=Run, flasher_on=8ms, flasher_off=8ms] Encoder'",
        "DF2: fix by hand, no migration reads profile=approach:toward=180",
        "Review in Address Editor -> Changed, then Sync to save",
    ]
    assert opened == ["changed"]


def test_cli_upgrade_project_with_nothing_to_do():
    store = _store({("X", 1): "[link=Run, on_delay=1s] Aux"})
    result = dispatch(DispatchContext(store=store), "tag upgrade-project")
    assert result == "upgrade project: every annotation is in the current form"
    assert not store.has_unsaved_changes()


def _app(store):
    from clicknick.app import ClickNickApp

    app = ClickNickApp.__new__(ClickNickApp)
    app._get_store = MagicMock(return_value=store)
    app._open_address_editor = MagicMock()
    app._update_status = MagicMock()
    app.repairs_menu = MagicMock()
    app._repairs_upgrade_project_index = 1
    app.root = SimpleNamespace()
    return app


def test_the_repairs_entry_is_enabled_while_an_old_form_remains():
    store = _store({("X", 1): ENCODER})
    app = _app(store)
    app._refresh_upgrade_entry()
    app.repairs_menu.entryconfigure.assert_called_with(1, state="normal")

    app._upgrade_project()
    app._open_address_editor.assert_called_once_with("changed")
    assert "Staged 1 comment upgrade(s)" in app._update_status.call_args.args[0]

    app._refresh_upgrade_entry()
    app.repairs_menu.entryconfigure.assert_called_with(1, state="disabled")


def test_the_repairs_entry_lists_comments_to_fix_by_hand(monkeypatch):
    from clicknick import app as app_module

    warnings: list[str] = []
    monkeypatch.setattr(
        app_module.messagebox, "showwarning", lambda _title, text, **_kw: warnings.append(text)
    )
    app = _app(_store({("DF", 2): STUCK}))
    app._upgrade_project()
    assert warnings and warnings[0].endswith("DF2")
    app._open_address_editor.assert_not_called()
