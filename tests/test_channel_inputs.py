"""Analog source classification reaches both in-memory and persisted checks."""

import pytest
from pyrung import Program, Rung, copy
from pyrung.click import ClickBlocks, TagMap, pyrung_to_ladder

from clicknick.services.analysis_service import (
    _build_graph,
    _channel_inputs,
    _regenerate_persisted_project,
    read_analog_inputs,
)


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
    read: list[object] = []

    def channel_inputs(scr_folder):
        read.append(scr_folder)
        return _channel_inputs(scr_folder)

    monkeypatch.setattr("clicknick.services.analysis_service._channel_inputs", channel_inputs)
    (tmp_path / "Project.ini").write_text(
        "[SystemConfig]\nItem1=192\n[CPUBuild]\nAD1=DF1,10,0\nDA1=DF5,10,0\n",
        encoding="utf-8",
    )
    graph, _program, project, _nicknames = _build_graph(tmp_path, None, tmp_path / "workspace")
    assert read == [tmp_path]  # One reading for the analysis and the workspace
    assert graph.tags["DF1"].external
    assert not graph.tags["DF10"].external
    namespace = {}
    exec((project / "src/plc/tags.py").read_text(encoding="utf-8"), namespace)
    assert namespace["df"][1].external
    assert not namespace["df"][5].external
    assert not namespace["df"][10].external
    # Recorded with the generation, for regenerating its code later
    assert read_analog_inputs(project / "csv") == {"DF1"}


@pytest.mark.parametrize("inputs", [frozenset(), frozenset({"DF1", "DF2"})])
def test_a_generated_workspace_records_its_analog_inputs(tmp_path, monkeypatch, inputs):
    def save(_source, destination, *, index):
        (destination / "main.csv").write_text("", encoding="utf-8")

    monkeypatch.setattr("clicknick.ladder.program.program_save", save)
    monkeypatch.setattr(
        "pyrung.click.ladder_to_pyrung_project",
        lambda _csv, *, output_dir, **_kwargs: (output_dir / "src" / "plc").mkdir(parents=True),
    )

    project = _regenerate_persisted_project(
        tmp_path, None, tmp_path / "workspace", analog_inputs=inputs
    )

    assert read_analog_inputs(project / "csv") == inputs
