"""Analog source classification reaches both in-memory and persisted checks."""

import pytest
from pyrung import Program, Rung, copy
from pyrung.click import ClickBlocks, TagMap, pyrung_to_ladder

from clicknick.services.analysis_service import _build_graph, _channel_inputs


def test_missing_channel_configuration_is_optional(tmp_path):
    assert _channel_inputs(tmp_path) == frozenset()


def test_invalid_channel_configuration_is_not_silently_ignored(tmp_path):
    (tmp_path / "Project.ini").write_text("not ini", encoding="utf-8")
    with pytest.raises(ValueError):
        _channel_inputs(tmp_path)


def test_channel_inputs_reach_analysis_and_generated_workspace(tmp_path, monkeypatch):
    blocks = ClickBlocks()
    with Program() as program:
        with Rung():
            copy(blocks.df[1], blocks.df[10])
    bundle = pyrung_to_ladder(program, TagMap([], include_system=False))

    def save(_source, destination, *, index):
        bundle.write(destination)

    monkeypatch.setattr("clicknick.ladder.program.program_save", save)
    (tmp_path / "Project.ini").write_text(
        "[SystemConfig]\nItem1=192\n[CPUBuild]\nAD1=DF1,10,0\nDA1=DF5,10,0\n",
        encoding="utf-8",
    )
    graph, _program, project = _build_graph(tmp_path, None, tmp_path / "workspace")
    assert graph.tags["DF1"].external
    assert not graph.tags["DF10"].external
    namespace = {}
    exec((project / "src/plc/tags.py").read_text(encoding="utf-8"), namespace)
    assert namespace["df"][1].external
    assert not namespace["df"][5].external
    assert not namespace["df"][10].external
