"""Static program analysis via pyrung's dependency graph.

Pure Python, no tkinter.  Builds a ProgramGraph from the connected
Click project's Scr*.tmp files and exposes tag-role and dependency
queries that return addr_key sets for address editor filtering.
"""

from __future__ import annotations

import codecs
import enum
import json
import shutil
import tempfile
import threading
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pyclickplc.addresses import get_addr_key, iter_address_slots
from pyrung.click import SystemNicknameRepair, SystemNicknameRepairRequired
from pyrung.click.tag_map import OldCommentFormError

if TYPE_CHECKING:
    from pyrung.core.analysis.pdg import ProgramGraph
    from pyrung.core.program import Program
    from pyrung.core.validation.report import ValidationReport

    from ..models.address_row import AddressRow
    from .program_check_selection import ProgramCheckSelection

WorkspaceKind = Literal["temporary", "persistent"]


def _is_old_comment_form(exc: BaseException) -> bool:
    """Return True if *exc*, or an error it wraps, is pyrung rejecting an old annotation form."""
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, OldCommentFormError):
            return True
        if getattr(current, "code", None) == OldCommentFormError.code:
            return True
        # ``raise X from Y`` inside an ``except`` sets both links, so follow each one.
        pending += [link for link in (current.__cause__, current.__context__) if link is not None]
    return False


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


def _read_nickname_rows(db_path: Path) -> dict[int, AddressRow]:
    """Read the saved CLICK nicknames once per build.

    The generated code, the persisted project and the tag map all come from
    this one snapshot, so tag names always match the code that uses them.
    """
    from ..utils.mdb_operations import MdbConnection, load_all_addresses

    with MdbConnection(str(db_path)) as conn:
        return load_all_addresses(conn)


def _write_nicknames_csv(csv_dir: Path, nickname_rows: Mapping[int, AddressRow]) -> Path:
    """Write the nickname snapshot to csv_dir/nicknames.csv for pyrung."""
    from ..data.data_source import CsvDataSource

    nick_dest = csv_dir / "nicknames.csv"
    CsvDataSource(str(nick_dest)).save_changes(list(nickname_rows.values()))
    return nick_dest


def _channel_inputs(scr_folder: Path) -> frozenset[str]:
    """Read installed analog input assignments alongside the saved ladder."""
    from pyclickplc.project import read_channel_parameters

    try:
        return read_channel_parameters(scr_folder / "Project.ini").inputs
    except FileNotFoundError:
        return frozenset()


#: File in a workspace's csv/ that lists the analog input channels it was generated with.
ANALOG_INPUTS_FILENAME = "analog_inputs.json"


def _write_analog_inputs(csv_dir: Path, inputs: frozenset[str]) -> None:
    text = json.dumps(sorted(inputs)) + "\n"
    (csv_dir / ANALOG_INPUTS_FILENAME).write_text(text, encoding="utf-8")


def read_analog_inputs(csv_dir: Path) -> frozenset[str]:
    """Return the analog input channels that the workspace holding *csv_dir* was generated with.

    pyrung marks them ``external``. Regenerating the workspace's code needs the same set.
    """
    path = csv_dir / ANALOG_INPUTS_FILENAME
    try:
        inputs = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(
            "the workspace has no record of its analog inputs. Reload the workspace from CLICK"
        ) from None
    if not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs):
        raise ValueError(f"{path} does not hold a list of addresses")
    return frozenset(inputs)


_TagMaps = tuple[dict[str, int], dict[int, str]]


def _build_tag_addr_key_map(
    nickname_csv: Path | None,
    nickname_rows: Mapping[int, AddressRow],
) -> _TagMaps:
    """Build bidirectional tag_name <-> addr_key maps over every address.

    pyrung reads the names from *nickname_csv*, the snapshot's nicknames.csv that the code
    was generated from (``tag_names``). So the names match the code with whichever pyrung is
    installed. An address with no nickname is named by its display address (e.g. "X001").
    """
    from .tag_names import tag_names

    keys = (get_addr_key(memory_type, address) for memory_type, address in iter_address_slots())
    key_to_tag = tag_names(nickname_csv, nickname_rows, keys)
    tag_to_key = {tag: addr_key for addr_key, tag in key_to_tag.items()}
    return tag_to_key, key_to_tag


_GENERATED_DIR_NAMES = {"src", "csv", "csv_output"}
_GENERATED_FILE_NAMES = {
    "nicknames.csv",
    "project_to_csv.py",
    "run.py",
    # pyrung's own guidance, rewritten with the program on every save.
    "AGENTS.pyrung.md",
    "README.pyrung.md",
}
#: The user's guidance files. ClickNick only keeps their pointer to pyrung's guidance.
_WORKSPACE_GUIDANCE_FILES = {"AGENTS.md", "README.md"}
#: The pointer line that pyrung seeds into each of them starts with this.
_GUIDANCE_MARKER = "<!-- pyrung:guidance -->"
#: An older pyrung wrote these files whole, and they contain this marker.
_OLD_GUIDANCE_MARKER = "<!-- pyrung:workspace-lifecycle:start -->"
_EXPORT_IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc")


def _clean_generated(persist_dir: Path, *, keep: frozenset[str] = frozenset()) -> None:
    """Remove ClickNick-owned outputs from an active workspace, except those named in *keep*."""
    for child in persist_dir.iterdir():
        managed = child.name in _GENERATED_DIR_NAMES or child.name in _GENERATED_FILE_NAMES
        if not managed or child.name in keep:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _copy_missing(source: Path, destination: Path) -> None:
    """Seed generated support files without replacing workspace-owned files."""
    if source.is_dir():
        for child in source.rglob("*"):
            relative = child.relative_to(source)
            target = destination / relative
            if child.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, target)
    elif not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _refresh_workspace_guidance(source: Path, destination: Path) -> None:
    """Keep the user's AGENTS.md / README.md pointing at pyrung's guidance file.

    The file belongs to the user. If its pointer line is missing, put it back on top and
    change nothing else. An older pyrung wrote some files whole, and they still carry that
    pyrung's markers. Such a file is all stale guidance, so move it aside to
    ``*.previous.md`` and put the fresh one in its place.
    """
    generated = source.read_text(encoding="utf-8")
    pointer = next(
        (line for line in generated.splitlines() if line.startswith(_GUIDANCE_MARKER)), None
    )
    if pointer is None:
        return
    # Only a pointer line is at stake. If the file is not UTF-8 (an ANSI file), or cannot be
    # read or replaced, leave it as it is and let the build go on.
    try:
        raw = destination.read_bytes()
        existing = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return
    if _GUIDANCE_MARKER in existing:
        return
    encoding = "utf-8-sig" if raw.startswith(codecs.BOM_UTF8) else "utf-8"
    newline = "\r\n" if b"\r\n" in raw else "\n"
    existing = existing.replace("\r\n", "\n")
    try:
        if _OLD_GUIDANCE_MARKER in existing:
            destination.replace(destination.with_name(f"{destination.stem}.previous.md"))
            refreshed = generated
            encoding, newline = "utf-8", None
        else:
            # Put the pointer under the file's title if it opens with one, otherwise on top.
            title, _, body = existing.partition("\n")
            if title.startswith("# "):
                body = body.lstrip("\n")
                refreshed = f"{title}\n\n{pointer}\n\n{body}"
            else:
                refreshed = f"{pointer}\n\n{existing}"
        staging = destination.with_suffix(f"{destination.suffix}.clicknick-guidance")
        try:
            staging.write_text(refreshed, encoding=encoding, newline=newline)
            staging.replace(destination)
        finally:
            staging.unlink(missing_ok=True)
    except OSError:
        pass


def _publish_generated_project(staged_dir: Path, persist_dir: Path) -> None:
    """Publish a complete staged generation without risking workspace edits.

    It waits for a backup or restore of the workspace that is under way. It holds the
    workspace from its backup of edits until the generation is recorded.
    """
    from .project_workspace import (
        _replace_tree,
        _replace_trees,
        backup_modified_plc_source,
        plc_source_dir,
        record_generated_plc_source,
        workspace_writing,
    )

    staged_source = plc_source_dir(staged_dir)
    if not staged_source.is_dir():
        raise ValueError(f"staged generated source directory not found: {staged_source}")

    persist_dir.mkdir(parents=True, exist_ok=True)
    with workspace_writing(persist_dir, wait=True):
        backup_modified_plc_source(persist_dir)

        # Copy support files first. csv/ and src/plc go last and together. So a failure
        # anywhere (a file open in Excel) never leaves csv/ from one save and src/plc from
        # another. The generation record is written only once both are in.
        for child in staged_dir.iterdir():
            if child.name in {"src", "csv"}:
                continue
            destination = persist_dir / child.name
            if child.name in _GENERATED_DIR_NAMES:
                _replace_tree(child, destination)
            elif child.name in _GENERATED_FILE_NAMES:
                shutil.copy2(child, destination)
            elif child.name in _WORKSPACE_GUIDANCE_FILES and destination.is_file():
                _refresh_workspace_guidance(child, destination)
            else:
                _copy_missing(child, destination)
        # Remove outputs that this generation does not write, such as csv_output/.
        _clean_generated(persist_dir, keep=frozenset(child.name for child in staged_dir.iterdir()))

        pairs = [(staged_source, plc_source_dir(persist_dir))]
        if (staged_dir / "csv").is_dir():
            pairs.insert(0, (staged_dir / "csv", persist_dir / "csv"))
        _replace_trees(pairs)
        record_generated_plc_source(persist_dir)


def _regenerate_persisted_project(
    scr_folder: Path,
    nickname_rows: Mapping[int, AddressRow] | None,
    persist_dir: Path,
    *,
    analog_inputs: frozenset[str],
    workspace_kind: WorkspaceKind = "temporary",
) -> Path:
    """Generate beside the workspace, then publish only a complete project.

    The function records *analog_inputs* in csv/, because `tag apply` regenerates the code
    from csv/.
    """
    from pyrung.click import ladder_to_pyrung_project

    from ..ladder.program import program_save

    persist_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{persist_dir.name}-regeneration-", dir=persist_dir.parent
    ) as stage_root:
        staged_dir = Path(stage_root) / "project"
        staged_dir.mkdir()
        csv_persist = staged_dir / "csv"
        csv_persist.mkdir()
        program_save(scr_folder, csv_persist, index=True)
        persist_nickname_csv = None
        if nickname_rows is not None:
            persist_nickname_csv = _write_nicknames_csv(csv_persist, nickname_rows)
        _write_analog_inputs(csv_persist, analog_inputs)

        ladder_to_pyrung_project(
            csv_persist,
            nickname_csv=persist_nickname_csv,
            analog_inputs=analog_inputs,
            output_dir=staged_dir,
            index=True,
            workspace_kind=workspace_kind,
        )
        _publish_generated_project(staged_dir, persist_dir)
    return persist_dir


def _build_graph(
    scr_folder: Path,
    db_path: Path | None,
    persist_dir: Path | None = None,
    *,
    workspace_kind: WorkspaceKind = "temporary",
    on_project_generated: Callable[[Path, _TagMaps], None] | None = None,
) -> tuple[ProgramGraph, Program, Path | None, _TagMaps]:
    """Run the full pipeline: Scr*.tmp -> CSV -> pyrung code -> exec -> graph.

    When *persist_dir* is provided, also writes the full pyrung project
    (src/plc/) to disk for consumption by DAP and
    rung apply commands.

    Return the graph, the program, the persisted project folder, and the tag maps of the
    nickname snapshot that the code was generated from. Without a database, the maps name
    every address by its display address.
    """
    from pyrung.click import ladder_to_pyrung
    from pyrung.core.analysis import build_program_graph

    from ..ladder.program import program_save

    nickname_rows = _read_nickname_rows(db_path) if db_path is not None else None
    # Read Project.ini once, like the nicknames, and use it for both the code and the workspace.
    analog_inputs = _channel_inputs(scr_folder)

    with tempfile.TemporaryDirectory(prefix="clicknick_analysis_") as tmp:
        csv_dir = Path(tmp)
        program_save(scr_folder, csv_dir, index=True)

        nickname_csv = None
        if nickname_rows is not None:
            nickname_csv = _write_nicknames_csv(csv_dir, nickname_rows)

        code = ladder_to_pyrung(csv_dir, nickname_csv=nickname_csv, analog_inputs=analog_inputs)
        tag_maps = _build_tag_addr_key_map(nickname_csv, nickname_rows or {})

    # Generated source is useful for inspection and repair even when executing
    # it cannot construct a Program. Publish it independently of analysis.
    project_dir = None
    if persist_dir is not None:
        project_dir = _regenerate_persisted_project(
            scr_folder,
            nickname_rows,
            persist_dir,
            analog_inputs=analog_inputs,
            workspace_kind=workspace_kind,
        )
        if on_project_generated is not None:
            on_project_generated(project_dir, tag_maps)

    namespace: dict[str, object] = {}
    exec(compile(code, "<analysis>", "exec"), namespace)  # noqa: S102
    program = namespace["logic"]

    from pyrung.core.program import Program

    if not isinstance(program, Program):
        msg = f"Expected Program, got {type(program).__name__}"
        raise TypeError(msg)

    graph = build_program_graph(program)
    return graph, program, project_dir, tag_maps


class AnalysisService:
    """Owns the program analysis lifecycle and exposes query methods."""

    def __init__(self) -> None:
        self.check_selection: ProgramCheckSelection | None = None
        self._result: AnalysisResult | None = None
        self._project_dir: Path | None = None
        # Tag names of the project in _project_dir, and whether the latest build wrote it.
        # If a rebuild fails after publishing, both are newer than _result. If it fails
        # before publishing, _project_dir is still an older save's.
        self._project_tags: dict[str, int] = {}
        self._project_keys: dict[int, str] = {}
        self._project_is_current = False
        # Written from the build thread, read from the UI thread. Plain
        # attribute assignment is atomic enough; there is no read-modify-write.
        self._status = AnalysisStatus.IDLE
        self._error: str | None = None
        self._error_detail: str | None = None
        self._system_nickname_repairs: tuple[SystemNicknameRepair, ...] = ()
        self._needs_comment_upgrade = False
        # Builds run on a worker thread while invalidate() runs on the Tk thread.
        # The lock makes epoch bumps and publish-if-current atomic.
        self._lock = threading.Lock()
        self._generation = 0
        self._epoch = 0
        # Number of build requests made (`mark_building`). A build that serves fewer requests
        # than this leaves the status BUILDING, because what it publishes is older than the
        # latest request.
        self._builds_asked = 0
        # A request failed before it could be queued while a build ran. Its reason and
        # detail are shown once the build that serves every request finishes.
        self._failed_request: tuple[str, str | None] | None = None

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

    @property
    def system_nickname_repairs(self) -> tuple[SystemNicknameRepair, ...]:
        """Structured vendor corrections when the current failure is repairable."""

        return self._system_nickname_repairs

    @property
    def needs_comment_upgrade(self) -> bool:
        """Return True if the build failed on a comment in an old annotation form."""
        return self._needs_comment_upgrade

    @property
    def project_is_current(self) -> bool:
        """Return True if ``project_dir`` holds what the latest build read from CLICK.

        It is False after a build failed before it published. ``project_dir`` is then the
        workspace of an earlier save.
        """
        return self._project_is_current

    @property
    def project_tag_to_addr_key(self) -> dict[str, int]:
        """Return the tag name -> addr_key map for the tag names in ``project_dir``'s source.

        It is the same as ``tag_to_addr_key`` unless a rebuild failed after publishing the
        workspace. In that case the graph and ``tag_to_addr_key`` stay the previous build's,
        while the workspace on disk already uses the new names.
        """
        return self._project_tags

    @property
    def project_addr_key_to_tag(self) -> dict[int, str]:
        """Return the addr_key -> tag name map for ``project_dir``'s source.

        See ``project_tag_to_addr_key``.
        """
        return self._project_keys

    def _record_failure(self, reason: str, detail: str | None) -> None:
        """Show *reason* as the latest request's outcome. The caller holds ``_lock``."""
        self._failed_request = None
        self._epoch += 1
        self._project_is_current = False
        self._status = AnalysisStatus.FAILED
        self._error = reason
        self._error_detail = detail
        self._system_nickname_repairs = ()
        self._needs_comment_upgrade = False

    def mark_failed(
        self, reason: str, detail: str | None = None, *, serves: int | None = None
    ) -> None:
        """Record a failure that the build thread never got to raise.

        Without *serves*, a request failed before it could be queued (no project database,
        no saved ladder files), so views can say *why* instead of waiting forever. While a
        build runs, the status stays BUILDING, and the failure shows once the build that
        serves every request finishes. A later request replaces it. With *serves*, the build
        for that request failed before ``build()`` ran. If that build serves fewer requests
        than were made, the status is left to the build queued after it.
        """
        with self._lock:
            if serves is None:
                if self._status is AnalysisStatus.BUILDING:
                    self._failed_request = (reason, detail)
                    return
            elif serves < self._builds_asked:
                return
            elif self._failed_request is not None:
                reason, detail = self._failed_request
            self._record_failure(reason, detail)

    def mark_building(self) -> int:
        """Report a queued build, so nobody sees a stale status until its thread starts.

        Return the number of builds asked for so far. Pass it to ``build(serves=)``.
        """
        with self._lock:
            self._builds_asked += 1
            self._failed_request = None
            self._status = AnalysisStatus.BUILDING
            self._error = None
            self._error_detail = None
            self._system_nickname_repairs = ()
            self._needs_comment_upgrade = False
            return self._builds_asked

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
        """Generated workspace, available even if program analysis failed."""
        if self._project_dir is not None:
            return self._project_dir
        if self._result is None:
            return None
        return self._result.project_dir

    def export_project(self, destination: Path) -> int:
        """Copy the ready generated project to a new or empty directory.

        The copy is staged beside *destination* and published only if no
        analysis rebuild started while files were being copied. Disposable
        virtual environments and Python caches are omitted.
        """
        if self._status is AnalysisStatus.BUILDING:
            raise RuntimeError("pyrung project is not ready to export")
        if self.project_dir is None:
            raise RuntimeError("pyrung project was not persisted to disk")

        source = self.project_dir.resolve()
        destination = destination.resolve()
        if not source.is_dir():
            raise RuntimeError(f"pyrung project folder does not exist: {source}")
        if destination == source or source in destination.parents or destination in source.parents:
            raise ValueError("export destination must be separate from the active project folder")
        if destination.exists():
            if not destination.is_dir():
                raise ValueError(f"export destination is not a directory: {destination}")
            if any(destination.iterdir()):
                raise FileExistsError(
                    f"export folder already exists and must be empty: {destination}"
                )
        if not destination.parent.is_dir():
            raise FileNotFoundError(
                f"export destination parent does not exist: {destination.parent}"
            )

        generation = self._generation
        with tempfile.TemporaryDirectory(
            prefix=f".{destination.name}-export-", dir=destination.parent
        ) as stage_root:
            staged = Path(stage_root) / "project"
            shutil.copytree(source, staged, ignore=_EXPORT_IGNORE)

            if (
                self._generation != generation
                or self._status is AnalysisStatus.BUILDING
                or self.project_dir is None
                or self.project_dir.resolve() != source
            ):
                raise RuntimeError(
                    "CLICK project changed during export. Try again after the conversion finishes."
                )

            file_count = sum(path.is_file() for path in staged.rglob("*"))
            if destination.exists():
                destination.rmdir()
            staged.replace(destination)
        return file_count

    def build(
        self,
        scr_folder: Path,
        db_path: Path | None,
        persist_dir: Path | None = None,
        workspace_kind: WorkspaceKind = "temporary",
        *,
        serves: int | None = None,
    ) -> bool:
        """Run the analysis pipeline and cache the result.

        Return True if the result was published, and False if invalidate() or a newer build
        superseded it while it ran. *serves* is the value that ``mark_building`` returned for
        the request this build serves. By default it is every request so far. If more
        requests were made since, the status stays BUILDING for the build that serves them.

        Called from a background thread; stores results for main-thread access.
        When *persist_dir* is given, the pyrung project is also written to disk.
        *workspace_kind* selects matching lifecycle guidance in generated docs.

        On failure the status becomes FAILED and the reason is recorded before
        the exception is re-raised — a caller that swallows it still leaves the
        UI able to explain itself. Any previous good result is kept, so a failed
        *rebuild* does not take working analysis away from open windows.
        """
        with self._lock:
            # Readers use this generation to detect a rebuild racing their work.
            self._generation += 1
            self._epoch += 1
            epoch = self._epoch
            if serves is None:
                serves = self._builds_asked
            self._project_is_current = False
            self._status = AnalysisStatus.BUILDING
            self._error = None
            self._error_detail = None
            self._system_nickname_repairs = ()
            self._needs_comment_upgrade = False

        def _project_generated(project_dir: Path, tag_maps: _TagMaps) -> None:
            with self._lock:
                if self._epoch == epoch:
                    self._project_dir = project_dir
                    self._project_tags, self._project_keys = tag_maps
                    self._project_is_current = True

        try:
            graph, program, project_dir, (tag_to_key, key_to_tag) = _build_graph(
                scr_folder,
                db_path,
                persist_dir,
                workspace_kind=workspace_kind,
                on_project_generated=_project_generated,
            )
        except Exception as exc:
            with self._lock:
                if self._epoch == epoch and serves >= self._builds_asked:
                    if self._failed_request is not None:
                        self._record_failure(*self._failed_request)
                    else:
                        self._status = AnalysisStatus.FAILED
                        self._error = f"{type(exc).__name__}: {exc}"
                        self._error_detail = traceback.format_exc()
                        if isinstance(exc, SystemNicknameRepairRequired):
                            self._system_nickname_repairs = exc.repairs
                        self._needs_comment_upgrade = _is_old_comment_form(exc)
            raise
        with self._lock:
            if self._epoch != epoch:
                return False
            self._project_dir = project_dir
            self._project_tags = tag_to_key
            self._project_keys = key_to_tag
            self._project_is_current = True
            self._result = AnalysisResult(
                graph=graph,
                program=program,
                tag_to_addr_key=tag_to_key,
                addr_key_to_tag=key_to_tag,
                project_dir=project_dir,
            )
            if serves >= self._builds_asked:
                if self._failed_request is not None:
                    self._record_failure(*self._failed_request)
                else:
                    self._status = AnalysisStatus.READY
        return True

    def invalidate(self) -> None:
        with self._lock:
            self._epoch += 1
            self._failed_request = None
            self._result = None
            self._project_dir = None
            self._project_tags = {}
            self._project_keys = {}
            self._project_is_current = False
            self._status = AnalysisStatus.IDLE
            self._error = None
            self._error_detail = None
            self._system_nickname_repairs = ()
            self._needs_comment_upgrade = False

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
        from pyrung.core.validation.config import CheckConfig, load_check_config

        if self.check_selection is not None:
            config = self.check_selection.load()
            if self.project_dir is not None:
                self.check_selection.sync(self.project_dir)
        else:
            config = (
                load_check_config(self.project_dir / "pyproject.toml") if self.project_dir else None
            ) or CheckConfig()
        return self._result.program.check(select=set(config.resolve()))
