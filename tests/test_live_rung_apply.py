"""Tests of what ``rung apply`` reports and what it passes to Review Changes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import ANY, Mock

import pytest
from laddercodec import Coil, Rung, write_csv

from clicknick.live import rung_commands
from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.services.project_workspace import (
    exported_source_state_path,
    plc_source_dir,
    plc_source_fingerprint,
    plc_source_is_exported,
    record_exported_plc_source,
    record_generated_plc_source,
)
from clicknick.services.rung_diff import BundleSources

CLICK = {
    "main.csv": ["Y001", "Y002"],
    "subroutines/Fill.csv": ["Y003"],
}


class _Store:
    def get_dirty_keys(self) -> set[int]:
        return set()


class _Analysis:
    is_available = True

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir


def _rungs(coils: list[str]) -> list[Rung]:
    return [
        Rung(
            conditions=[["-"] * 31],
            instructions=[Coil(coil)],
            comment=None,
        )
        for coil in coils
    ]


def _write_bundle(root: Path, programs: dict[str, list[str]]) -> None:
    for name, coils in programs.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(path, _rungs(coils), index=True)


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    """Return a workspace whose export writes whatever ``propose`` was given.

    The fixture returns ``(context, propose, staged)``. The context is the dispatch context
    with a mock Review Changes. ``propose`` sets the next export. ``staged`` holds the
    staged counts.
    """
    _write_bundle(tmp_path / "csv", CLICK)
    source = tmp_path / "src" / "plc"
    (source / "subroutines").mkdir(parents=True)
    (source / "main.py").write_text("main\n", encoding="utf-8")
    (source / "subroutines" / "__init__.py").write_text("", encoding="utf-8")
    for stem, title in (("fill", "Fill"), ("rinse_cycle", "Rinse Cycle")):
        (source / "subroutines" / f"{stem}.py").write_text(
            f'@subroutine("{title}")\ndef {stem}(): ...\n', encoding="utf-8"
        )

    proposal: dict[str, list[str]] = {}

    def _export(project_dir: Path) -> Path:
        _write_bundle(project_dir / "csv_output", proposal)
        return project_dir / "csv_output"

    monkeypatch.setattr(rung_commands, "_run_export", _export)
    staged: list[int] = []
    ctx = DispatchContext(
        store=_Store(),
        analysis=_Analysis(tmp_path),
        show_proposal=Mock(),
        record_staged_rungs=staged.append,
    )
    return ctx, proposal.update, staged


def test_reports_every_program_that_differs_and_opens_review_changes(
    project, tmp_path: Path
) -> None:
    ctx, propose, staged = project
    propose(
        {
            "main.csv": ["Y001", "Y005", "Y002"],
            "subroutines/Rinse Cycle.csv": ["Y006"],  # New. The proposal has no Fill.
        }
    )

    reply = dispatch(ctx, "rung apply")

    # The files come in the order Review Changes walks them: subroutines before main.
    assert "changed files:\n  rinse_cycle: new, 1 rung\n  main: R2\n" in reply
    assert (
        "only in CLICK: Fill. To delete a subroutine that you no longer use, first paste main's "
        "changes in Review Changes. Then, in CLICK, make sure that the main program no longer "
        "calls the subroutine. After that, right-click the subroutine in the list of programs "
        "and click Delete."
    ) in reply
    assert staged == [2]
    ctx.show_proposal.assert_called_once_with(
        tmp_path / "csv_output", tmp_path / "src" / "plc", None, None, True
    )


def test_a_subroutine_only_in_click_beside_an_unchanged_main_goes_straight_to_click(
    project,
) -> None:
    ctx, propose, _staged = project
    propose({"main.csv": CLICK["main.csv"]})  # The proposal has no Fill

    reply = dispatch(ctx, "rung apply")

    assert "changed files:" not in reply
    assert (
        "\nonly in CLICK: Fill. To delete a subroutine that you no longer use, do this in CLICK: "
        "make sure that the main program no longer calls the subroutine. After that, right-click "
        "the subroutine in the list of programs and click Delete.\n"
    ) in reply


def test_unchanged_proposal_only_refreshes_an_open_window(project, tmp_path: Path) -> None:
    ctx, propose, staged = project
    propose(CLICK)

    reply = dispatch(ctx, "rung apply")

    assert "(no changes)" in reply
    assert staged == [0]
    ctx.show_proposal.assert_called_once_with(
        tmp_path / "csv_output", tmp_path / "src" / "plc", None, None, False
    )


def test_removed_rungs_are_reported_and_counted(project) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001"]})

    reply = dispatch(ctx, "rung apply")

    assert "  main: removes CLICK's R2" in reply
    assert staged == [1]


def test_one_file_opens_review_changes_on_that_program(project, tmp_path: Path) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y006", "Y002"]})

    reply = dispatch(ctx, "rung apply main")

    assert "OK: opened Review Changes for main (R2..3)" in reply
    assert staged == [2]
    ctx.show_proposal.assert_called_once_with(
        tmp_path / "csv_output", tmp_path / "src" / "plc", "main.csv", None, True
    )


def test_selection_names_the_rungs_to_paste(project, tmp_path: Path) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y002"]})

    reply = dispatch(ctx, "rung apply main --select r1..2")

    assert "OK: opened Review Changes for main (2 selected rungs)" in reply
    assert staged == [2]
    ctx.show_proposal.assert_called_once_with(
        tmp_path / "csv_output", tmp_path / "src" / "plc", "main.csv", [1, 2], True
    )


def test_selection_of_rungs_click_already_has_is_no_change(project) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y002"]})

    reply = dispatch(ctx, "rung apply main --select r1,r3")

    assert "(no changes)" in reply
    assert staged == [0]
    assert ctx.show_proposal.call_args.args[-1] is False


def test_new_subroutine_file_is_found_by_its_title(project) -> None:
    ctx, propose, _staged = project
    propose({**CLICK, "subroutines/Rinse Cycle.csv": ["Y006", "Y007"]})

    reply = dispatch(ctx, "rung apply rinse_cycle")

    assert "OK: opened Review Changes for rinse_cycle (new, 2 rungs)" in reply
    assert ctx.show_proposal.call_args.args[2] == "subroutines/Rinse Cycle.csv"


def test_file_the_export_left_out_is_an_error(project) -> None:
    ctx, propose, _staged = project
    propose(CLICK)

    with pytest.raises(ValueError, match="rinse_cycle was not exported"):
        dispatch(ctx, "rung apply rinse_cycle")


def test_without_a_window_one_file_replies_with_its_diff(project) -> None:
    ctx, propose, _staged = project
    ctx.show_proposal = None
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y002"]})

    reply = dispatch(ctx, "rung apply main")

    assert (
        "--- CLICK/main.csv\n+++ workspace/main.csv\n"
        " R1  out(Y001)\n+R2  out(Y005)\n R3  out(Y002)\n"
    ) in reply


def _earlier_export(project_dir: Path) -> tuple[Path, Path]:
    """Write an export that holds main.csv and a subroutine the source no longer has."""
    main = project_dir / "csv_output" / "main.csv"
    stale = project_dir / "csv_output" / "subroutines" / "Deleted.csv"
    stale.parent.mkdir(parents=True)
    main.write_text("earlier", encoding="utf-8")
    stale.write_text("stale", encoding="utf-8")
    return main, stale


def test_export_drops_csvs_it_did_not_write_again(tmp_path: Path) -> None:
    main, stale = _earlier_export(tmp_path)
    (tmp_path / "project_to_csv.py").write_text(
        "from pathlib import Path\n"
        "out = Path(__file__).parent / 'csv_output'\n"
        "(out / 'main.csv').write_text('fresh', encoding='utf-8')\n",
        encoding="utf-8",
    )

    rung_commands._run_export(tmp_path)

    assert main.read_text(encoding="utf-8") == "fresh"
    assert not stale.exists()


# A project_to_csv.py that writes a rung_sources.json with one rung for each with rung() line
_MANIFEST_SCRIPT = """\
import json
from pathlib import Path

here = Path(__file__).parent
main = here / "src" / "plc" / "main.py"
starts = [
    number
    for number, line in enumerate(main.read_text(encoding="utf-8").splitlines(), start=1)
    if "with rung()" in line
]
sources = [
    {"source_file": str(main), "source_line": line, "end_line": line + 1} for line in starts
]
(here / "csv_output").mkdir(exist_ok=True)
(here / "csv_output" / "rung_sources.json").write_text(
    json.dumps(
        {
            "version": 1,
            "main": [
                {"rung": rung, "sources": [source]}
                for rung, source in enumerate(sources, start=1)
            ],
            "subroutines": {},
        }
    ),
    encoding="utf-8",
)
"""


def _manifest_workspace(project_dir: Path, source: str, script: str = _MANIFEST_SCRIPT) -> Path:
    """Write a workspace whose main.py holds *source*, and return main.py."""
    main = project_dir / "src" / "plc" / "main.py"
    main.parent.mkdir(parents=True)
    main.write_text(source, encoding="utf-8")
    (project_dir / "project_to_csv.py").write_text(script, encoding="utf-8")
    return main


def test_export_records_the_source_that_it_read(tmp_path: Path) -> None:
    main = _manifest_workspace(tmp_path, "with rung():\n    pass\n")

    rung_commands._run_export(tmp_path)

    assert plc_source_is_exported(tmp_path)
    main.write_text("with rung():\n    out(Y001)\n", encoding="utf-8")
    assert not plc_source_is_exported(tmp_path)


def test_export_records_the_source_as_it_read_it_before_the_export_ran(tmp_path: Path) -> None:
    edits_main = _MANIFEST_SCRIPT + 'main.write_text("with rung():\\n    out(Y001)\\n")\n'
    _manifest_workspace(tmp_path, "with rung():\n    pass\n", edits_main)

    rung_commands._run_export(tmp_path)

    assert not plc_source_is_exported(tmp_path)


def test_an_export_that_writes_no_manifest_leaves_no_record(tmp_path: Path) -> None:
    main = _manifest_workspace(tmp_path, "with rung():\n    pass\n")
    rung_commands._run_export(tmp_path)
    manifest = tmp_path / "csv_output" / "rung_sources.json"
    assert manifest.is_file()
    main.write_text("with rung():\n    out(Y001)\n", encoding="utf-8")
    (tmp_path / "project_to_csv.py").write_text("pass\n", encoding="utf-8")

    rung_commands._run_export(tmp_path)

    assert not manifest.exists()
    assert not exported_source_state_path(tmp_path).exists()
    assert not plc_source_is_exported(tmp_path)


_TWO_RUNGS = "with rung():\n    pass\nwith rung():\n    pass\n"


def _exported_twice(tmp_path: Path, second_script: str) -> tuple[bytes, bytes]:
    """Export ``_TWO_RUNGS``, edit main.py, and export again with *second_script*.

    Return the manifest and the record that the first export wrote.
    """
    main = _manifest_workspace(tmp_path, _TWO_RUNGS)
    rung_commands._run_export(tmp_path)
    manifest = (tmp_path / "csv_output" / "rung_sources.json").read_bytes()
    record = exported_source_state_path(tmp_path).read_bytes()
    main.write_text("with rung():\n    pass\n" + _TWO_RUNGS, encoding="utf-8")
    (tmp_path / "project_to_csv.py").write_text(second_script, encoding="utf-8")
    return manifest, record


def test_a_failed_export_puts_back_the_earlier_manifest_and_record(tmp_path: Path) -> None:
    # The script writes another manifest, and then fails
    writes_then_fails = _MANIFEST_SCRIPT + "raise SystemExit('broken')\n"
    manifest, record = _exported_twice(tmp_path, writes_then_fails)

    with pytest.raises(ValueError, match="broken"):
        rung_commands._run_export(tmp_path)

    assert (tmp_path / "csv_output" / "rung_sources.json").read_bytes() == manifest
    assert exported_source_state_path(tmp_path).read_bytes() == record
    assert not list((tmp_path / "csv_output").glob("*.aside"))


def test_an_export_that_times_out_puts_back_the_earlier_manifest_and_record(
    tmp_path: Path, monkeypatch
) -> None:
    manifest, record = _exported_twice(tmp_path, _MANIFEST_SCRIPT)

    def _times_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", _times_out)
    with pytest.raises(subprocess.TimeoutExpired):
        rung_commands._run_export(tmp_path)

    assert (tmp_path / "csv_output" / "rung_sources.json").read_bytes() == manifest
    assert exported_source_state_path(tmp_path).read_bytes() == record


def test_an_export_writes_no_record_if_the_manifest_cannot_be_set_aside(
    tmp_path: Path, monkeypatch
) -> None:
    _exported_twice(tmp_path, _MANIFEST_SCRIPT)
    replace = Path.replace

    def _locked(path: Path, target):
        if path.name == "rung_sources.json":
            raise PermissionError("in use")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", _locked)
    rung_commands._run_export(tmp_path)

    assert not exported_source_state_path(tmp_path).exists()
    assert not plc_source_is_exported(tmp_path)


def test_review_changes_reads_the_earlier_manifest_after_a_failed_export(tmp_path: Path) -> None:
    _exported_twice(tmp_path, "raise SystemExit('broken')\n")

    with pytest.raises(ValueError, match="broken"):
        rung_commands._run_export(tmp_path)

    sources = BundleSources.workspace(plc_source_dir(tmp_path), tmp_path / "csv_output")
    assert sources.lines("main.csv") == {1: [1], 2: [3]}


def test_failed_export_leaves_the_earlier_one_alone(tmp_path: Path) -> None:
    main, stale = _earlier_export(tmp_path)
    (tmp_path / "project_to_csv.py").write_text("raise SystemExit('broken')\n", encoding="utf-8")

    with pytest.raises(ValueError, match="broken"):
        rung_commands._run_export(tmp_path)

    assert main.read_text(encoding="utf-8") == "earlier"
    assert stale.exists()


def test_export_of_a_workspace_with_markers_names_each_rung(tmp_path: Path, monkeypatch) -> None:
    """Build a workspace from CLICK rungs that laddercodec cannot read, then export it.

    pyrung's export refuses undecoded(). ClickNick names CLICK's program and rung for each
    call, and tells the user not to delete the call.
    """
    from laddercodec import Call, Program, UnknownCondition

    from clicknick.services.analysis_service import AnalysisService

    def _rung(output: str, first: object = "-") -> Rung:
        return Rung([[first, *["-"] * 30]], [Coil(output)], None)

    bad = UnknownCondition(raw=b"Compare")
    programs = {
        b"Scr1.tmp": Program(
            "Main Program",
            1,
            [
                _rung("C1"),
                Rung([["-"] * 31], [Call("Fill Tank")], None),
                _rung("C2", bad),
                _rung("C3"),
            ],
        ),
        b"Scr2.tmp": Program("Fill Tank", 2, [_rung("C10"), _rung("C11", bad)]),
    }
    monkeypatch.setattr("clicknick.ladder.program.decode_program", programs.__getitem__)
    monkeypatch.setattr("clicknick.services.analysis_service._channel_inputs", lambda _s: [])
    scr = tmp_path / "scr"
    scr.mkdir()
    for name in programs:
        (scr / name.decode()).write_bytes(name)
    workspace = tmp_path / "pyrung_project"
    assert AnalysisService().build(scr, None, persist_dir=workspace)

    with pytest.raises(ValueError) as refused:
        rung_commands._run_export(workspace)

    assert str(refused.value) == (
        "ClickNick cannot export the workspace. Its src/plc holds undecoded() in place of "
        "rung 3 of Main Program and rung 2 of Fill Tank, because ClickNick could not read "
        "those rungs from CLICK. CLICK has no instruction for undecoded(). In src/plc, write "
        "each rung's logic in place of its call. Or do this in CLICK for each rung that "
        "ClickNick cannot read: click its number to select the rung, and paste the rung again. "
        "Then save."
    )


def test_an_export_that_fails_for_another_reason_keeps_its_traceback(tmp_path: Path) -> None:
    (tmp_path / "project_to_csv.py").write_text("raise KeyError('lost')\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"(?s)Traceback.*KeyError: 'lost'"):
        rung_commands._run_export(tmp_path)


def test_summary_names_rungs_in_an_old_encoding_and_rungs_that_cannot_be_read() -> None:
    from clicknick.ladder.program import LegacyEncoding
    from clicknick.services.rung_diff import compare_rungs

    rungs = _rungs(["Y001", "Y002", "Y003"])
    found = [
        LegacyEncoding("main.csv", "Main Program", 1, "Math", "H70000", "it is stored..."),
        LegacyEncoding("main.csv", "Main Program", 3, "Compare", "", "it is refused.", True),
    ]

    summary = rung_commands._describe_change(compare_rungs(rungs, rungs, found), new=False)

    assert summary == (
        "R1, R3; CLICK's R1 in an old encoding; CLICK's R3 unreadable; paste it whole"
    )


def test_a_program_click_holds_unreadable_is_never_no_change(project, tmp_path: Path) -> None:
    """Report main as changed although its text matches, because CLICK's R2 is unreadable.

    The user must paste the whole program again.
    """
    from clicknick.ladder.program import LegacyEncoding, write_legacy_encodings

    ctx, propose, _staged = project
    propose(CLICK)
    found = LegacyEncoding("main.csv", "Main Program", 2, "Compare", "", "x", unreadable=True)
    write_legacy_encodings(tmp_path / "csv", [found])

    reply = dispatch(ctx, "rung apply")

    assert "  main: R2; CLICK's R2 unreadable; paste it whole" in reply
    assert "(no changes)" not in reply
    selected = dispatch(ctx, "rung apply main --select r1")
    # Selecting rung 1 does not paste it alone. CLICK's R2 is unreadable, so the whole program
    # is pasted.
    assert "OK: opened Review Changes for main (R2; CLICK's R2 unreadable; paste it whole)" in (
        selected
    )
    ctx.show_proposal.assert_called_with(ANY, ANY, "main.csv", None, True)


class _Status:
    def __init__(self, value: str) -> None:
        self.value = value


class _UnbuiltAnalysis:
    is_available = False
    project_dir = None

    def __init__(self, status: str, error: str | None = None) -> None:
        self.status = _Status(status)
        self.error = error


def test_a_failed_build_gives_its_reason() -> None:
    ctx = DispatchContext(store=_Store(), analysis=_UnbuiltAnalysis("failed", "no Scr*.tmp files"))

    with pytest.raises(ValueError) as caught:
        dispatch(ctx, "rung list")

    assert str(caught.value) == "Could not build the workspace: no Scr*.tmp files"


def test_an_unknown_program_is_named(tmp_path: Path) -> None:
    (tmp_path / "src" / "plc").mkdir(parents=True)
    ctx = DispatchContext(store=_Store(), analysis=_Analysis(tmp_path))

    with pytest.raises(ValueError) as caught:
        dispatch(ctx, "rung list nosuch")

    assert str(caught.value) == (
        "There is no program named 'nosuch'. Run 'rung list' to see the names."
    )


# ---------------------------------------------------------------------------
# rung list
# ---------------------------------------------------------------------------

# A rung was added in the workspace without a marker, so the markers below it are stale
_EDITED_MAIN = """\
with Program() as logic:
    with rung():  # R1
        out(A)

    with rung():
        out(Added)

    with rung():  # R2
        out(B)
"""

_MARKERS_NOTE = (
    "NOTE: These numbers come from the # R1, # R2, ... comments in main.py. Those comments can "
    "be out of date, so rung apply --select may count the rungs differently. To number them as "
    "rung apply does, run rung apply or open Review Changes, then run rung list again.\n"
)


def _source(path: Path, line: int) -> dict:
    return {"source_file": str(path), "source_line": line, "end_line": line + 1}


def _manifest(main: Path, *lines: int) -> dict:
    """Return a manifest that gives main's rungs 1, 2 and so on the source *lines*.

    A line of 0 stands for a rung with no source line in main.py.
    """
    return {
        "version": 1,
        "main": [
            {"rung": rung, "sources": [_source(main, line)] if line else []}
            for rung, line in enumerate(lines, start=1)
        ],
        "subroutines": {},
    }


def _listed(
    tmp_path: Path,
    monkeypatch,
    manifest: dict | None,
    *,
    exported: str = _EDITED_MAIN,
    generated: str | None = None,
    restored: bool = False,
) -> str:
    """Return the reply to ``rung list main``, for a main.py that holds ``_EDITED_MAIN``.

    The last export wrote *manifest* as ``rung_sources.json`` from a main.py that held
    *exported*. If *manifest* is None, there was no export. *generated* is what main.py held
    when ClickNick last generated the workspace, or None if there is no record of it. If
    *restored* is set, main.py is dated a second before the export, as a restore leaves it.
    """
    main = tmp_path / "src" / "plc" / "main.py"
    main.parent.mkdir(parents=True)
    if generated is not None:
        main.write_text(generated, encoding="utf-8")
        record_generated_plc_source(tmp_path)
    if manifest is not None:
        main.write_text(exported, encoding="utf-8")
        written = tmp_path / "csv_output" / "rung_sources.json"
        written.parent.mkdir()
        written.write_text(json.dumps(manifest), encoding="utf-8")
        record_exported_plc_source(tmp_path, plc_source_fingerprint(tmp_path))
    main.write_text(_EDITED_MAIN, encoding="utf-8")
    if restored:
        exported_at = (tmp_path / "csv_output" / "rung_sources.json").stat().st_mtime_ns
        os.utime(main, ns=(exported_at - 10**9, exported_at - 10**9))

    return _list_main(tmp_path, monkeypatch)


def _list_main(project_dir: Path, monkeypatch) -> str:
    """Return the reply to ``rung list main``, and fail if it runs the export."""

    def _no_export(project_dir: Path) -> Path:
        raise AssertionError("rung list ran the export")

    monkeypatch.setattr(rung_commands, "_run_export", _no_export)
    return dispatch(
        DispatchContext(store=_Store(), analysis=_Analysis(project_dir)), "rung list main"
    )


def test_rung_list_numbers_the_rungs_from_an_export_of_the_source_as_it_is(
    tmp_path: Path, monkeypatch
) -> None:
    main = tmp_path / "src" / "plc" / "main.py"

    reply = _listed(tmp_path, monkeypatch, _manifest(main, 2, 5, 8, 0))

    assert reply.startswith(
        "main: 4 rungs\n"
        "  R1: 3 lines\n"
        "  R2: 3 lines\n"
        "  R3: 2 lines\n"
        "  R4: no source line in this file"
    )


def test_rung_list_reads_the_markers_when_the_source_changed_since_the_export(
    tmp_path: Path, monkeypatch
) -> None:
    main = tmp_path / "src" / "plc" / "main.py"
    manifest = _manifest(main, 2, 5, 8)
    before = _EDITED_MAIN.replace("out(Added)", "out(Other)")

    reply = _listed(tmp_path, monkeypatch, manifest, exported=before)

    assert reply.startswith(f"{_MARKERS_NOTE}main: 2 rungs\n  R1: 6 lines\n  R2: 2 lines")


def test_rung_list_reads_the_markers_after_a_restore_puts_back_an_older_file(
    tmp_path: Path, monkeypatch
) -> None:
    """A restore puts back main.py with its old time.

    That time is older than the export of the file that main.py replaced.
    """
    main = tmp_path / "src" / "plc" / "main.py"
    manifest = _manifest(main, 2, 5, 8)
    before = _EDITED_MAIN.replace("out(Added)", "out(Other)")

    reply = _listed(tmp_path, monkeypatch, manifest, exported=before, restored=True)

    assert reply.startswith(f"{_MARKERS_NOTE}main: 2 rungs\n")


def test_rung_list_reads_the_markers_after_project_to_csv_runs_by_hand(
    tmp_path: Path, monkeypatch
) -> None:
    """The source goes back to what rung apply exported, but the manifest is from another source."""
    main = _manifest_workspace(tmp_path, _EDITED_MAIN)
    rung_commands._run_export(tmp_path)
    main.write_text("with Program() as logic:\n" + _EDITED_MAIN, encoding="utf-8")
    subprocess.run([sys.executable, "project_to_csv.py"], cwd=tmp_path, check=True)
    main.write_text(_EDITED_MAIN, encoding="utf-8")

    reply = _list_main(tmp_path, monkeypatch)

    assert reply.startswith(f"{_MARKERS_NOTE}main: 2 rungs\n  R1: 6 lines\n  R2: 2 lines")


def test_rung_list_reads_the_markers_without_an_export(tmp_path: Path, monkeypatch) -> None:
    reply = _listed(tmp_path, monkeypatch, None)

    assert reply.startswith(f"{_MARKERS_NOTE}main: 2 rungs\n  R1: 6 lines\n  R2: 2 lines")


def test_rung_list_shows_no_note_for_the_source_as_clicknick_generated_it(
    tmp_path: Path, monkeypatch
) -> None:
    reply = _listed(tmp_path, monkeypatch, None, generated=_EDITED_MAIN)

    assert reply.startswith("main: 2 rungs\n  R1: 6 lines\n  R2: 2 lines")


def test_rung_list_reads_the_markers_when_the_export_names_a_line_outside_every_rung(
    tmp_path: Path, monkeypatch
) -> None:
    main = tmp_path / "src" / "plc" / "main.py"

    # Line 1 is the with Program() line, which no with rung() block holds
    reply = _listed(tmp_path, monkeypatch, _manifest(main, 2, 5, 1))

    assert reply.startswith(
        "NOTE: These numbers come from the # R1, # R2, ... comments in main.py. The last export "
        "ties a rung to a line of main.py that is not inside a with rung() block, so rung list "
        "cannot use that export. The comments can be out of date, so rung apply --select may "
        "count the rungs differently.\n"
        "main: 2 rungs\n"
    )
