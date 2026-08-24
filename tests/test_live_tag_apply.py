"""Tests for the ``tag apply`` live command.

``tag apply`` exports the pristine (baseline) and edited (current) ``tags.py``,
diffs the two exports so only the agent's real edits survive, lands them as one
batched unsaved change, and asks the GUI to open the Address Editor filtered to
"Changed". The diff-of-two-exports is what cancels pyrung's systematic
round-trip artifacts (``[external]`` inference, bank-default retentive/initial on
unnamed slots, hex padding) — see ``_compute_tag_changes``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.live import tag_commands
from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.live.tag_commands import _compute_tag_changes


class MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def load_all_addresses(self):
        return {}

    def save_changes(self, rows):
        return len(rows)


class MockAnalysis:
    is_available = True

    def __init__(self, project_dir):
        self.project_dir = project_dir


@pytest.fixture
def store():
    s = AddressStore(MockDataSource())
    s.load_initial_data()
    return s


def _row(store, mem, addr):
    return store.get_visible_row(get_addr_key(mem, addr))


# --- pure diff core --------------------------------------------------------


def test_no_edits_yields_no_changes(store):
    # Baseline and current exports identical -> nothing to apply.
    base = {get_addr_key("DS", 1): _row(store, "DS", 1)}
    assert _compute_tag_changes(base, dict(base), store) == []


def test_rename_detected(store):
    key = get_addr_key("DS", 1)
    base = {key: _row(store, "DS", 1)}
    cur = {key: replace(base[key], nickname="Setpoint")}
    assert _compute_tag_changes(base, cur, store) == [(key, "nickname", "Setpoint")]


def test_new_tag_on_empty_slot_counts_only_set_fields(store):
    # Address absent from baseline (a brand-new nickname) -> compared to default.
    key = get_addr_key("DS", 2)
    cur_row = replace(_row(store, "DS", 2), nickname="NewTag", initial_value="0")
    changes = _compute_tag_changes({}, {key: cur_row}, store)
    # nickname is set; initial_value "0" is the numeric default -> not a change.
    assert changes == [(key, "nickname", "NewTag")]


def test_initial_value_default_normalization(store):
    # base "" vs current "0" on a numeric are both default -> not a change.
    key = get_addr_key("DS", 1)
    base = {key: replace(_row(store, "DS", 1), initial_value="")}
    cur = {key: replace(_row(store, "DS", 1), initial_value="0")}
    assert _compute_tag_changes(base, cur, store) == []


def test_initial_value_real_change_detected(store):
    key = get_addr_key("DS", 1)
    base = {key: replace(_row(store, "DS", 1), initial_value="0")}
    cur = {key: replace(_row(store, "DS", 1), initial_value="5")}
    assert _compute_tag_changes(base, cur, store) == [(key, "initial_value", "5")]


def test_comment_and_retentive_changes_detected(store):
    key = get_addr_key("DS", 1)
    base = {key: _row(store, "DS", 1)}
    cur = {key: replace(base[key], comment="[uom=degF]", retentive=not base[key].retentive)}
    changes = _compute_tag_changes(base, cur, store)
    assert (key, "comment", "[uom=degF]") in changes
    assert (key, "retentive", not base[key].retentive) in changes


def test_address_not_in_store_is_skipped(store):
    # A row the store does not track (bogus key) must not crash or apply.
    bogus = 10_000_000
    fake = replace(_row(store, "DS", 1), nickname="X")
    assert _compute_tag_changes({}, {bogus: fake}, store) == []


# --- dispatch integration (export step monkeypatched) ----------------------


def _patch_exports(monkeypatch, base, cur):
    monkeypatch.setattr(tag_commands, "_load_export_rows", lambda project_dir: (base, cur))


def test_tag_apply_applies_and_opens_changed(store, tmp_path, monkeypatch):
    key = get_addr_key("DS", 1)
    base = {key: _row(store, "DS", 1)}
    cur = {key: replace(base[key], nickname="Setpoint", comment="target")}
    _patch_exports(monkeypatch, base, cur)

    opened: list[str] = []
    ctx = DispatchContext(
        store=store, analysis=MockAnalysis(tmp_path), show_address_editor=opened.append
    )
    result = dispatch(ctx, "tag apply")

    assert "1 tag changed" in result
    assert opened == ["changed"]
    row = store.get_visible_row(key)
    assert row.nickname == "Setpoint"
    assert row.comment == "target"
    assert store.is_dirty(key)


def test_tag_apply_batches_single_undo_frame(store, tmp_path, monkeypatch):
    k1, k2 = get_addr_key("DS", 1), get_addr_key("DS", 2)
    base = {k1: _row(store, "DS", 1), k2: _row(store, "DS", 2)}
    cur = {k1: replace(base[k1], nickname="A"), k2: replace(base[k2], nickname="B")}
    _patch_exports(monkeypatch, base, cur)

    ctx = DispatchContext(store=store, analysis=MockAnalysis(tmp_path))
    assert "2 tags changed" in dispatch(ctx, "tag apply")

    store.undo()  # one frame reverts both
    assert not store.is_dirty(k1)
    assert not store.is_dirty(k2)


def test_tag_apply_no_changes_leaves_editor_closed(store, tmp_path, monkeypatch):
    base = {get_addr_key("DS", 1): _row(store, "DS", 1)}
    _patch_exports(monkeypatch, base, dict(base))

    opened: list[str] = []
    ctx = DispatchContext(
        store=store, analysis=MockAnalysis(tmp_path), show_address_editor=opened.append
    )
    assert "no changes" in dispatch(ctx, "tag apply")
    assert opened == []


def test_tag_apply_requires_project(store):
    # No analysis -> no persisted project dir -> clear error, not a crash.
    with pytest.raises(ValueError, match="analysis not available"):
        dispatch(DispatchContext(store=store), "tag apply")


def test_load_export_rows_reads_src_plc_tags(tmp_path, monkeypatch):
    from clicknick.data import data_source
    from clicknick.live import rung_commands

    tags_dir = tmp_path / "src" / "plc"
    tags_dir.mkdir(parents=True)
    (tags_dir / "tags.py").write_text("current tags\n", encoding="utf-8")

    monkeypatch.setattr(
        rung_commands,
        "_get_before_files",
        lambda _project_dir: {"src/plc/tags.py": "baseline tags\n"},
    )
    exported: list[str] = []
    monkeypatch.setattr(
        tag_commands,
        "_export_nicknames",
        lambda source, _path: exported.append(source),
    )

    class FakeDataSource:
        def __init__(self, path):
            self.path = path

        def load_all_addresses(self):
            return {self.path: self.path}

    monkeypatch.setattr(data_source, "CsvDataSource", FakeDataSource)

    tag_commands._load_export_rows(tmp_path)

    assert exported == ["baseline tags\n", "current tags\n"]
