"""Analog source classification reaches both in-memory and persisted checks."""

import pytest
from pyrung import Program, copy, rung
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
        with rung():
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
    dataview, _program, project, _tag_maps = _build_graph(tmp_path, None, tmp_path / "workspace")
    assert read == [tmp_path]  # The analysis and the workspace read the project once between them
    details = dataview.details()
    assert details["DF1"].external
    assert not details["DF10"].external
    namespace = {}
    exec((project / "src/plc/tags.py").read_text(encoding="utf-8"), namespace)
    assert namespace["df"][1].external
    assert not namespace["df"][5].external
    assert not namespace["df"][10].external
    # The generation records the analog inputs, so its code can be regenerated later.
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


def _write_empty_program(monkeypatch):
    blocks = ClickBlocks()
    with Program() as program:
        with rung():
            copy(blocks.df[1], blocks.df[10])
    bundle = pyrung_to_ladder(program, TagMap([], include_system=False))
    monkeypatch.setattr(
        "clicknick.ladder.program.program_save",
        lambda _source, destination, *, index: bundle.write(destination),
    )


# -1 is not a CLICK module ID, so pyclickplc's catalog never has it. A real ID that
# pyclickplc has not catalogued yet would become known once pyclickplc adds it.
@pytest.mark.parametrize(
    ("text", "warned"),
    [
        ("[SystemConfig]\nItem1=196\nItem10=-1\n", "does not know: Option slot 0 (module ID -1)"),
        ("not ini", "could not read the hardware configuration"),
    ],
    ids=["unknown module", "malformed"],
)
def test_a_project_ini_that_pyclickplc_cannot_fully_read_does_not_stop_the_build(
    tmp_path, monkeypatch, text, warned
):
    _write_empty_program(monkeypatch)
    (tmp_path / "Project.ini").write_text(text, encoding="utf-8")
    warnings: list[str] = []

    dataview, _program, project, _tag_maps = _build_graph(
        tmp_path, None, tmp_path / "workspace", on_warning=warnings.append
    )

    assert not dataview.details()["DF1"].external
    assert read_analog_inputs(project / "csv") == frozenset()
    assert len(warnings) == 1
    assert warned in warnings[0]
    assert "analog input" in warnings[0]


def test_an_unknown_expansion_keeps_the_analog_inputs_of_the_known_cpu(tmp_path, monkeypatch):
    # 241 is the C0-02DD1-D, which has analog inputs. -1 is not a CLICK module ID.
    _write_empty_program(monkeypatch)
    (tmp_path / "Project.ini").write_text(
        "[SystemConfig]\nItem1=241\nItem2=-1\n[CPUBuild]\nAD1=DF1,10,0\n", encoding="utf-8"
    )
    warnings: list[str] = []

    dataview, _program, project, _tag_maps = _build_graph(
        tmp_path, None, tmp_path / "workspace", on_warning=warnings.append
    )

    assert dataview.details()["DF1"].external
    assert read_analog_inputs(project / "csv") == frozenset({"DF1"})
    assert len(warnings) == 1
    assert "does not know: Expansion 1 (module ID -1)." in warnings[0]
    assert "goes on with the analog inputs of the other modules" in warnings[0]


def test_an_unknown_cpu_warns_that_only_the_expansion_modules_are_read(tmp_path, monkeypatch):
    # 999 is not a CLICK module ID, so pyclickplc reads no option slot.
    _write_empty_program(monkeypatch)
    (tmp_path / "Project.ini").write_text("[SystemConfig]\nItem1=999\n", encoding="utf-8")
    warnings: list[str] = []

    _build_graph(tmp_path, None, tmp_path / "workspace", on_warning=warnings.append)

    assert len(warnings) == 1
    assert "does not know: CPU (module ID 999)." in warnings[0]
    assert "reads the analog inputs of only the expansion modules that it knows" in warnings[0]
    assert "the CPU, its option slots and the modules" in warnings[0]
    assert "the other modules" not in warnings[0]


def test_an_unreadable_project_ini_file_still_stops_the_build(tmp_path, monkeypatch):
    _write_empty_program(monkeypatch)

    def refuse(_scr_folder):
        raise PermissionError("locked")

    monkeypatch.setattr("clicknick.services.analysis_service._channel_inputs", refuse)
    with pytest.raises(PermissionError):
        _build_graph(tmp_path, None, tmp_path / "workspace")


def test_the_analysis_service_keeps_the_build_warning(tmp_path, monkeypatch):
    from clicknick.services.analysis_service import AnalysisService

    _write_empty_program(monkeypatch)
    (tmp_path / "Project.ini").write_text(
        "[SystemConfig]\nItem1=196\nItem10=-1\n", encoding="utf-8"
    )
    service = AnalysisService()
    service.mark_building()

    assert service.build(tmp_path, None, tmp_path / "workspace")

    assert "Option slot 0 (module ID -1)" in service.build_warning


def test_an_empty_option_slot_does_not_hide_the_analog_inputs_of_the_next_slot(tmp_path):
    # CLICK 4.00 saves a CLICK PLUS option slot that holds no module as module 8192 (C2-FILL).
    # Slot 1 holds a C2-08D1-4VC (8208), with two analog inputs and two analog outputs.
    record = "3,1,10.0,0.0,100.0,0.0,{},0.0122085215,0.0000000000,"
    channels = "12,1,DF499,1,DF498,6,0,0,0,0,1\t" + "\t".join(
        record.format(address) for address in ("DF1", "DF2", "DF3", "DF4")
    )
    (tmp_path / "Project.ini").write_text(
        "[SystemConfig]\nItem1=200\nItem10=8192\nItem11=8208\n"
        f"[SystemConfigData]\nItem11={channels}\n",
        encoding="utf-8",
    )
    assert _channel_inputs(tmp_path) == frozenset({"DF1", "DF2"})
