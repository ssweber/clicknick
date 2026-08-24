"""Static program analysis via pyrung's dependency graph.

Pure Python, no tkinter.  Builds a ProgramGraph from the connected
Click project's Scr*.tmp files and exposes tag-role and dependency
queries that return addr_key sets for address editor filtering.
"""

from __future__ import annotations

import enum
import tempfile
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrung.core.analysis.pdg import ProgramGraph
    from pyrung.core.program import Program
    from pyrung.core.validation.report import ValidationReport


class AnalysisStatus(enum.Enum):
    """Lifecycle of the pyrung conversion.

    Views poll this instead of only ``is_available``, which cannot tell
    "still building" apart from "failed and never coming".
    """

    IDLE = "idle"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


@dataclass
class AnalysisResult:
    """Cached analysis output."""

    graph: ProgramGraph
    program: Program
    tag_to_addr_key: dict[str, int] = field(default_factory=dict)
    addr_key_to_tag: dict[int, str] = field(default_factory=dict)
    role_cache: dict[str, set[int]] = field(default_factory=dict)
    project_dir: Path | None = None


def _write_nicknames_csv(csv_dir: Path, db_path: Path) -> Path | None:
    """Export nicknames from MDB to csv_dir/nicknames.csv."""
    nick_dest = csv_dir / "nicknames.csv"
    try:
        from ..data.data_source import CsvDataSource
        from ..utils.mdb_operations import MdbConnection, load_all_addresses

        with MdbConnection(str(db_path)) as conn:
            all_rows = load_all_addresses(conn)
        CsvDataSource(str(nick_dest)).save_changes(list(all_rows.values()))
        return nick_dest
    except Exception:
        return None


def _build_tag_addr_key_map(
    base_state: Mapping[int, object],
) -> tuple[dict[str, int], dict[int, str]]:
    """Build bidirectional tag_name <-> addr_key maps from base-layer rows.

    pyrung tags are named by raw Click nicknames.  Addresses with no
    nickname become tags named after the display_address (e.g. "X001").
    """
    tag_to_key: dict[str, int] = {}
    key_to_tag: dict[int, str] = {}

    for addr_key, row in base_state.items():
        nickname = getattr(row, "nickname", "")
        display = getattr(row, "display_address", "")
        tag = nickname.strip() if nickname else ""
        if tag:
            tag_to_key[tag] = addr_key
            key_to_tag[addr_key] = tag
        elif display:
            tag_to_key[display] = addr_key
            key_to_tag[addr_key] = display

    return tag_to_key, key_to_tag


_PRESERVE = {".venv", "__pycache__", "pyproject.toml", "tests", "uv.lock"}
_GENERATED_TEST_FILES = {"conftest.py", "test_smoke.py"}


def _clean_generated(persist_dir: Path) -> None:
    """Remove generated files while preserving environments and custom tests."""
    import shutil

    for child in persist_dir.iterdir():
        if child.name == "tests" and child.is_dir():
            for generated_name in _GENERATED_TEST_FILES:
                (child / generated_name).unlink(missing_ok=True)
            shutil.rmtree(child / "__pycache__", ignore_errors=True)
            continue
        if child.name in _PRESERVE:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _build_graph(
    scr_folder: Path, db_path: Path | None, persist_dir: Path | None = None
) -> tuple[ProgramGraph, Program, Path | None]:
    """Run the full pipeline: Scr*.tmp -> CSV -> pyrung code -> exec -> graph.

    When *persist_dir* is provided, also writes the full pyrung project
    (src/plc/) to disk for consumption by DAP and
    rung preview commands.
    """
    from pyrung.click import ladder_to_pyrung
    from pyrung.core.analysis import build_program_graph

    from ..ladder.program import program_save

    with tempfile.TemporaryDirectory(prefix="clicknick_analysis_") as tmp:
        csv_dir = Path(tmp)
        program_save(scr_folder, csv_dir, index=True)

        nickname_csv = None
        if db_path is not None:
            nickname_csv = _write_nicknames_csv(csv_dir, db_path)

        code = ladder_to_pyrung(csv_dir, nickname_csv=nickname_csv)

        project_dir = None
        if persist_dir is not None:
            from pyrung.click import ladder_to_pyrung_project

            persist_dir.mkdir(parents=True, exist_ok=True)
            _clean_generated(persist_dir)

            csv_persist = persist_dir / "csv"
            csv_persist.mkdir(exist_ok=True)
            program_save(scr_folder, csv_persist, index=True)
            persist_nickname_csv = None
            if db_path is not None:
                persist_nickname_csv = _write_nicknames_csv(csv_persist, db_path)

            ladder_to_pyrung_project(
                csv_persist,
                nickname_csv=persist_nickname_csv,
                output_dir=persist_dir,
                index=True,
            )
            project_dir = persist_dir

    namespace: dict[str, object] = {}
    exec(compile(code, "<analysis>", "exec"), namespace)  # noqa: S102
    program = namespace["logic"]

    from pyrung.core.program import Program

    if not isinstance(program, Program):
        msg = f"Expected Program, got {type(program).__name__}"
        raise TypeError(msg)

    return build_program_graph(program), program, project_dir


class AnalysisService:
    """Owns the program analysis lifecycle and exposes query methods."""

    def __init__(self) -> None:
        self._result: AnalysisResult | None = None
        # Written from the build thread, read from the UI thread. Plain
        # attribute assignment is atomic enough; there is no read-modify-write.
        self._status = AnalysisStatus.IDLE
        self._error: str | None = None
        self._error_detail: str | None = None
        self._generation = 0

    @property
    def is_available(self) -> bool:
        return self._result is not None

    @property
    def status(self) -> AnalysisStatus:
        return self._status

    @property
    def generation(self) -> int:
        """Bumped when a build starts, i.e. when the project folder is rewritten.

        Consumers that read the generated project off disk capture this before
        they start and compare afterwards: a change means the files moved under
        them and whatever they saw was a half-written project, not a real error.
        """
        return self._generation

    @property
    def error(self) -> str | None:
        """One-line reason the conversion failed, or None."""
        return self._error

    @property
    def error_detail(self) -> str | None:
        """Full traceback for a failed conversion, or None."""
        return self._error_detail

    def mark_failed(self, reason: str, detail: str | None = None) -> None:
        """Record a failure the build thread never got to raise.

        Used for pre-flight bail-outs (no project database, no saved ladder
        files) so views can say *why* instead of waiting forever.
        """
        self._status = AnalysisStatus.FAILED
        self._error = reason
        self._error_detail = detail

    @property
    def tag_to_addr_key(self) -> dict[str, int]:
        """Tag name → addr_key map (empty if analysis not built)."""
        if self._result is None:
            return {}
        return self._result.tag_to_addr_key

    @property
    def addr_key_to_tag(self) -> dict[int, str]:
        """addr_key → tag name map (empty if analysis not built)."""
        if self._result is None:
            return {}
        return self._result.addr_key_to_tag

    @property
    def project_dir(self) -> Path | None:
        """Path to the persisted pyrung_project/ directory (None if not built)."""
        if self._result is None:
            return None
        return self._result.project_dir

    def build(
        self,
        scr_folder: Path,
        db_path: Path | None,
        base_state: Mapping[int, object],
        persist_dir: Path | None = None,
    ) -> None:
        """Run the analysis pipeline and cache the result.

        Called from a background thread; stores results for main-thread access.
        When *persist_dir* is given, the pyrung project is also written to disk.

        On failure the status becomes FAILED and the reason is recorded before
        the exception is re-raised — a caller that swallows it still leaves the
        UI able to explain itself. Any previous good result is kept, so a failed
        *rebuild* does not take working analysis away from open windows.
        """
        # Bumped first: _build_graph empties the project folder before writing
        # it, so from this moment anything reading that folder sees rubble.
        self._generation += 1
        self._status = AnalysisStatus.BUILDING
        self._error = None
        self._error_detail = None
        try:
            graph, program, project_dir = _build_graph(scr_folder, db_path, persist_dir)
            tag_to_key, key_to_tag = _build_tag_addr_key_map(base_state)
        except Exception as exc:
            self._status = AnalysisStatus.FAILED
            self._error = f"{type(exc).__name__}: {exc}"
            self._error_detail = traceback.format_exc()
            raise
        self._result = AnalysisResult(
            graph=graph,
            program=program,
            tag_to_addr_key=tag_to_key,
            addr_key_to_tag=key_to_tag,
            project_dir=project_dir,
        )
        self._status = AnalysisStatus.READY

    def rebuild_mapping(self, base_state: Mapping[int, object]) -> None:
        """Refresh the tag<->addr_key mapping after a base_state change."""
        if self._result is None:
            return
        tag_to_key, key_to_tag = _build_tag_addr_key_map(base_state)
        self._result.tag_to_addr_key = tag_to_key
        self._result.addr_key_to_tag = key_to_tag
        self._result.role_cache.clear()

    def invalidate(self) -> None:
        self._result = None
        self._status = AnalysisStatus.IDLE
        self._error = None
        self._error_detail = None

    def known_tag_names(self) -> frozenset[str]:
        """Tag names present in both the graph and the addr_key map."""
        if self._result is None:
            return frozenset()
        graph_tags = frozenset(self._result.graph.tag_roles)
        mapped_tags = frozenset(self._result.tag_to_addr_key)
        return graph_tags & mapped_tags

    def get_role_keys(self, role: str) -> set[int]:
        """Return addr_keys for tags with the given role.

        role is one of: "input", "output" (TERMINAL), "pivot", "isolated".
        """
        if self._result is None:
            return set()

        cached = self._result.role_cache.get(role)
        if cached is not None:
            return cached

        from pyrung.core.analysis.pdg import TagRole

        role_map = {
            "input": TagRole.INPUT,
            "output": TagRole.TERMINAL,
            "pivot": TagRole.PIVOT,
            "isolated": TagRole.ISOLATED,
        }
        target_role = role_map.get(role)
        if target_role is None:
            return set()

        keys: set[int] = set()
        for tag_name, tag_role in self._result.graph.tag_roles.items():
            if tag_role is target_role:
                addr_key = self._result.tag_to_addr_key.get(tag_name)
                if addr_key is not None:
                    keys.add(addr_key)

        self._result.role_cache[role] = keys
        return keys

    def get_upstream_keys(self, tag_name: str) -> set[int]:
        """Return addr_keys for all tags transitively upstream of tag_name."""
        if self._result is None:
            return set()
        upstream_tags = self._result.graph.upstream_slice(tag_name)
        return {
            self._result.tag_to_addr_key[t]
            for t in upstream_tags
            if t in self._result.tag_to_addr_key
        }

    def get_downstream_keys(self, tag_name: str) -> set[int]:
        """Return addr_keys for all tags transitively downstream of tag_name."""
        if self._result is None:
            return set()
        downstream_tags = self._result.graph.downstream_slice(tag_name)
        return {
            self._result.tag_to_addr_key[t]
            for t in downstream_tags
            if t in self._result.tag_to_addr_key
        }

    def run_validation(self) -> ValidationReport | None:
        if self._result is None:
            return None
        from pyrung.core.validation import validate

        return validate(self._result.program)
