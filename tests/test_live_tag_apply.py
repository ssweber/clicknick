"""Tests for the ``tag apply`` live command.

``tag apply`` exports the pristine (baseline) and edited (current) ``tags.py``,
diffs the two exports so only the agent's real edits survive, lands them as one
batched staged change, and asks the GUI to open the Address Editor filtered to
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
    monkeypatch.setattr(
        tag_commands, "_load_export_rows", lambda _project_dir, *, analog_inputs: (base, cur)
    )


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
    with pytest.raises(ValueError, match="workspace not available"):
        dispatch(DispatchContext(store=store), "tag apply")


def test_load_export_rows_reads_src_plc_tags(tmp_path, monkeypatch):
    from clicknick.data import data_source
    from clicknick.live import rung_commands

    tags_dir = tmp_path / "src" / "plc"
    tags_dir.mkdir(parents=True)
    (tags_dir / "tags.py").write_text("current tags\n", encoding="utf-8")

    regenerated_with: list[frozenset[str]] = []

    def _before_files(_project_dir, *, analog_inputs):
        regenerated_with.append(analog_inputs)
        return {"src/plc/tags.py": "baseline tags\n"}

    monkeypatch.setattr(rung_commands, "_get_before_files", _before_files)
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

    tag_commands._load_export_rows(tmp_path, analog_inputs=frozenset({"DF1"}))

    assert exported == ["baseline tags\n", "current tags\n"]
    assert regenerated_with == [frozenset({"DF1"})]


# --- a real workspace generated from CLICK's nicknames -----------------------


class RowsDataSource(MockDataSource):
    def __init__(self, rows):
        self.rows = rows

    def load_all_addresses(self):
        return dict(self.rows)


def _generated_workspace(tmp_path, monkeypatch, rows, *, project_ini: str | None = None):
    """Generate a workspace from *rows* the way a CLICK save does; return (store, ctx)."""
    from pyrung import Program, Rung, copy
    from pyrung.click import ClickBlocks, TagMap, pyrung_to_ladder

    from clicknick.services import analysis_service

    blocks = ClickBlocks()
    with Program() as program:
        with Rung():
            copy(blocks.ds[1], blocks.ds[10])
            copy(blocks.df[1], blocks.df[10])
    bundle = pyrung_to_ladder(program, TagMap([], include_system=False))
    monkeypatch.setattr(
        "clicknick.ladder.program.program_save",
        lambda _source, destination, *, index: bundle.write(destination),
    )
    monkeypatch.setattr(analysis_service, "_read_nickname_rows", lambda _db: rows)
    click_folder = tmp_path / "click"
    click_folder.mkdir()
    if project_ini is not None:
        (click_folder / "Project.ini").write_text(project_ini, encoding="utf-8")
    _graph, _program, project, _rows = analysis_service._build_graph(
        click_folder, click_folder / "SC_.mdb", tmp_path / "workspace"
    )
    store = AddressStore(RowsDataSource(rows))
    store.load_initial_data()
    ctx = DispatchContext(store=store, analysis=MockAnalysis(project))
    if project_ini is not None:
        ctx.scr_folder = click_folder
    return store, ctx


def _edit_tags_py(ctx, old: str, new: str) -> None:
    tags = ctx.analysis.project_dir / "src" / "plc" / "tags.py"
    text = tags.read_text(encoding="utf-8")
    assert text.count(old) == 1, text
    tags.write_text(text.replace(old, new), encoding="utf-8")


def _rows(**comments):
    from pyclickplc.banks import DataType

    from clicknick.models.address_row import AddressRow

    names = {
        "DS1": ("Tank_Level", DataType.INT),
        "DS2": ("Tank_Temp", DataType.INT),
        "DS3": ("Tank_Out", DataType.INT),
        "DS10": ("Level_Copy", DataType.INT),
        "DF1": ("Level_In", DataType.FLOAT),
        "DF10": ("Level_Scaled", DataType.FLOAT),
    }
    rows = {}
    for display, (nickname, data_type) in names.items():
        mem, addr = display.rstrip("0123456789"), int(display.lstrip("DSF"))
        rows[get_addr_key(mem, addr)] = AddressRow(
            mem, addr, nickname=nickname, comment=comments.get(display, ""), data_type=data_type
        )
    return rows


def test_tag_apply_keeps_the_comment_text_and_block_tag_tags_py_leaves_out(tmp_path, monkeypatch):
    rows = _rows(DS1="<Tank> Level in tank 3", DS2="[uom=degC] temp", DS3="</Tank>")
    store, ctx = _generated_workspace(tmp_path, monkeypatch, rows)
    _edit_tags_py(ctx, "ds.slot(1, name='Tank_Level')", "ds.slot(1, name='Tank_Level', uom='mm')")
    _edit_tags_py(ctx, "uom='degC'", "uom='degF'")

    assert "2 tags changed" in dispatch(ctx, "tag apply")

    assert _row(store, "DS", 1).comment == "<Tank> [uom=mm] Level in tank 3"
    assert _row(store, "DS", 2).comment == "[uom=degF] temp"
    assert store.get_dirty_keys() == {get_addr_key("DS", 1), get_addr_key("DS", 2)}


_ANALOG_INPUT_DF1 = "[SystemConfig]\nItem1=192\n[CPUBuild]\nAD1=DF1,10,0\nDA1=DF5,10,0\n"


def test_tag_apply_on_an_unedited_workspace_leaves_analog_inputs_alone(tmp_path, monkeypatch):
    rows = _rows(DF1="Level in")
    store, ctx = _generated_workspace(tmp_path, monkeypatch, rows, project_ini=_ANALOG_INPUT_DF1)

    assert "no changes" in dispatch(ctx, "tag apply")

    _edit_tags_py(
        ctx, "df.slot(10, name='Level_Scaled')", "df.slot(10, name='Level_Scaled', uom='mm')"
    )
    assert "1 tag changed" in dispatch(ctx, "tag apply")
    assert store.get_dirty_keys() == {get_addr_key("DF", 10)}
    assert _row(store, "DF", 1).comment == "Level in"


def test_tag_apply_keeps_annotations_tags_py_did_not_change(store):
    # The store's comment gained [readonly] after the workspace was generated.
    key = get_addr_key("DS", 1)
    with store.edit_session("user") as session:
        session.set_field(key, "comment", "[readonly] Setpoint")
    base = {key: replace(_row(store, "DS", 1), comment="")}
    cur = {key: replace(base[key], comment="[uom=mm]")}

    changes = _compute_tag_changes(base, cur, store)

    assert changes == [(key, "comment", "[readonly, uom=mm] Setpoint")]


def test_tag_apply_refuses_annotations_that_clash_with_the_comment(store):
    key = get_addr_key("DS", 1)
    with store.edit_session("user") as session:
        session.set_field(key, "comment", "[choices=Off:0|On:1] Mode")
    base = {key: replace(_row(store, "DS", 1), comment="")}
    cur = {key: replace(base[key], comment="[min=0, max=10]")}

    with pytest.raises(ValueError, match="DS1"):
        _compute_tag_changes(base, cur, store)
