"""Static program analysis via pyrung's dependency graph.

This module is pure Python and does not use tkinter. It builds pyrung's DataView of the
program in the Scr*.tmp files of the connected CLICK project. Its queries about tag roles and dependencies
return sets of addr_keys, and the address editor filters its rows by those sets.
"""

from __future__ import annotations

import codecs
import enum
import json
import shutil
import tempfile
import threading
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pyclickplc.addresses import get_addr_key, iter_address_slots
from pyrung.click import OldCommentFormError, SystemNicknameRepair, SystemNicknameRepairRequired

if TYPE_CHECKING:
    from pyrung import DataView, Program
    from pyrung.validation import ValidationReport

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

    dataview: DataView
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
    """Return the addresses assigned to the analog inputs of the installed CLICK hardware.

    Read them from the Project.ini in *scr_folder*, beside the saved ladder files. Return an
    empty set if there is no Project.ini.
    """
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
            "The workspace has no record of its analog inputs. Use Workspace > Reload from "
            "CLICK to rebuild it."
        ) from None
    if not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs):
        raise ValueError(f"{path} does not hold a list of addresses")
    return frozenset(inputs)


_TagMaps = tuple[dict[str, int], dict[int, str]]


def _build_tag_addr_key_map(
    nickname_csv: Path | None,
    nickname_rows: Mapping[int, AddressRow],
) -> _TagMaps:
    """Return the tag_name -> addr_key map and the addr_key -> tag_name map of every address.

    ``tag_names`` gets the names by asking pyrung to read *nickname_csv*. That file is the
    nicknames.csv of the snapshot that the code was generated from. The names therefore match
    the code, whichever version of pyrung is installed. An address with no nickname is named
    by its display address (e.g. "X001").
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
#: The user's guidance files. ClickNick changes them only to put back a missing line that
#: points to pyrung's guidance. There is one exception. A file that an older pyrung wrote in
#: full is renamed to ``*.previous.md``, and pyrung's generated file takes its place.
_WORKSPACE_GUIDANCE_FILES = {"AGENTS.md", "README.md"}
#: The pointer line that pyrung writes into each of them starts with this.
_GUIDANCE_MARKER = "<!-- pyrung:guidance -->"
#: An older pyrung wrote all of the text in these files, and such a file contains this marker.
_OLD_GUIDANCE_MARKER = "<!-- pyrung:workspace-lifecycle:start -->"
_EXPORT_IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc")


def _clean_generated(persist_dir: Path, *, keep: frozenset[str] = frozenset()) -> None:
    """Remove the folders and files that ClickNick generates from *persist_dir*.

    Leave those named in *keep*.
    """
    for child in persist_dir.iterdir():
        managed = child.name in _GENERATED_DIR_NAMES or child.name in _GENERATED_FILE_NAMES
        if not managed or child.name in keep:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _copy_missing(source: Path, destination: Path) -> None:
    """Copy *source*, a file or a folder, to *destination* in the workspace.

    Do not replace a file that is already there.
    """
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

    The file belongs to the user. If its pointer line is missing, put it back under the
    file's title, or on top if the file has no title. Change nothing else, with one
    exception. An older pyrung wrote all of the text in some of these files, and such a file
    still contains that pyrung's marker. All of its text is out-of-date guidance. Rename it
    to ``*.previous.md`` and write the file that pyrung has just generated in its place.
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
    """Copy a fully generated project from *staged_dir* into the workspace *persist_dir*.

    If the user edited the workspace's src/plc, back it up first so that the edits are not
    lost. Wait for any backup or restore of the workspace that is under way. Hold the
    workspace's lock from that backup until the new source is recorded as generated.
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

        # Copy the support files first. Replace csv/ and src/plc last, and together, so that a
        # failure such as a file open in Excel never leaves csv/ from one save beside src/plc
        # from another. The generation record is written only after both are replaced.
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
    """Generate the pyrung project in a temporary folder beside *persist_dir*, then copy it in.

    Return *persist_dir*. The workspace receives the project only after the whole project has
    been generated. The function records *analog_inputs* in csv/, because `tag apply`
    regenerates the code from csv/.
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
) -> tuple[DataView, Program, Path | None, _TagMaps]:
    """Run the full pipeline: Scr*.tmp -> CSV -> pyrung code -> exec -> DataView.

    When *persist_dir* is provided, also writes the full pyrung project
    (src/plc/) to disk for consumption by DAP and
    rung apply commands.

    Return the program's DataView, the program, the persisted project folder, and the tag maps of the
    nickname snapshot that the code was generated from. Without a database, the maps name
    every address by its display address.
    """
    from pyrung.click import ladder_to_pyrung

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

    # Write the generated source to the workspace before running it. The user can inspect
    # and repair the source even if running it does not produce a Program.
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

    from pyrung import Program

    if not isinstance(program, Program):
        msg = (
            "The generated code must define logic as a pyrung Program. It defined a "
            f"{type(program).__name__}."
        )
        raise TypeError(msg)

    # The first dataview() call builds the dependency graph. Build it here, on the build
    # worker, and not on the Tk thread at the first query.
    return program.dataview(), program, project_dir, tag_maps


class AnalysisService:
    """Owns the program analysis lifecycle and exposes query methods."""

    def __init__(self) -> None:
        self.check_selection: ProgramCheckSelection | None = None
        self._result: AnalysisResult | None = None
        self._project_dir: Path | None = None
        # The tag maps of the project in _project_dir, and whether the latest build wrote
        # that project. If a rebuild fails after it writes the workspace, _project_dir and
        # these maps are newer than _result. If it fails before, _project_dir still holds the
        # workspace of an earlier save.
        self._project_tags: dict[str, int] = {}
        self._project_keys: dict[int, str] = {}
        self._project_is_current = False
        # The build thread writes these, and the UI thread reads them. Each write is a plain
        # assignment and never a read-modify-write, so it is atomic enough.
        self._status = AnalysisStatus.IDLE
        self._error: str | None = None
        self._error_detail: str | None = None
        self._system_nickname_repairs: tuple[SystemNicknameRepair, ...] = ()
        self._needs_comment_upgrade = False
        # Builds run on a worker thread, and invalidate() runs on the Tk thread. The lock
        # makes each increase of _epoch atomic. It also makes a build's check that _epoch is
        # unchanged and the storing of its result one atomic step.
        self._lock = threading.Lock()
        self._generation = 0
        self._epoch = 0
        # The number of build requests made so far. Each call to `mark_building` adds one. A
        # build that serves fewer requests than this leaves the status BUILDING, because its
        # result is older than the latest request.
        self._builds_asked = 0
        # If a request fails before it can be queued while a build runs, this holds its reason
        # and detail. The failure is shown once the build that serves every request finishes.
        self._failed_request: tuple[str, str | None] | None = None

    @property
    def is_available(self) -> bool:
        return self._result is not None

    @property
    def status(self) -> AnalysisStatus:
        return self._status

    @property
    def generation(self) -> int:
        """Return a counter that increases by one each time a build starts.

        A build may rewrite the project folder. A caller that reads the generated project
        from disk reads this counter before and after. If the value changed, a build rewrote
        the files while the caller read them. What the caller saw was then a half-written
        project, and an error it met there is not a real error.
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
        """Return the corrections to CLICK's system nicknames that the current failure needs.

        pyrung lists them in the error that it raises when a system nickname needs a
        correction. For any other failure, and when there is no failure, the tuple is empty.
        """

        return self._system_nickname_repairs

    @property
    def needs_comment_upgrade(self) -> bool:
        """Return True if the build failed on a comment in an old annotation form."""
        return self._needs_comment_upgrade

    @property
    def project_is_current(self) -> bool:
        """Return True if ``project_dir`` holds what the latest build read from CLICK.

        It is False after a build failed before it wrote the workspace. ``project_dir`` is
        then the workspace of an earlier save.
        """
        return self._project_is_current

    @property
    def project_tag_to_addr_key(self) -> dict[str, int]:
        """Return the tag name -> addr_key map for the tag names in ``project_dir``'s source.

        It is the same as ``tag_to_addr_key`` unless a rebuild failed after it wrote the
        workspace. In that case the DataView and ``tag_to_addr_key`` stay the previous build's,
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
        """Set the status to FAILED, with *reason* as the outcome of the latest request.

        The caller must hold ``_lock``.
        """
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

        Call it without *serves* when a request fails before it can be queued, for example
        because there is no project database or no saved ladder file. Views can then say
        *why* instead of waiting forever. If a build is running, the status stays BUILDING.
        The failure is shown once the build that serves every request finishes, unless a
        later request is made first and discards it.

        Call it with *serves*, the value that ``mark_building`` returned for a request, when
        the build for that request failed before ``build()`` ran.
        If that build serves fewer requests than were made, this call does nothing, and the
        build queued after it sets the status.
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
        """Set the status to BUILDING as soon as a build is queued.

        Views then do not show an old status while they wait for the build's thread to start.

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

        Return the number of files copied. The files go first to a temporary folder beside
        *destination*. That folder is moved to *destination* only if no analysis rebuild
        started while the files were copied. Virtual environments and Python caches are left
        out.
        """
        if self._status is AnalysisStatus.BUILDING:
            raise RuntimeError("The workspace is still being prepared. Try again in a moment.")
        if self.project_dir is None:
            raise RuntimeError(
                "There is no workspace to export. Save the project in CLICK, then try again."
            )

        source = self.project_dir.resolve()
        destination = destination.resolve()
        if not source.is_dir():
            raise RuntimeError(f"The workspace folder {source} does not exist.")
        if destination == source or source in destination.parents or destination in source.parents:
            raise ValueError(
                f"The export folder and the workspace {source} overlap. Choose another parent "
                "folder."
            )
        if destination.exists():
            if not destination.is_dir():
                raise ValueError(f"{destination} is a file. Choose another parent folder.")
            if any(destination.iterdir()):
                raise FileExistsError(
                    f"{destination} already exists and is not empty. Choose another parent "
                    "folder, or empty that folder."
                )
        if not destination.parent.is_dir():
            raise FileNotFoundError(
                f"The folder {destination.parent} does not exist. Choose a folder that exists."
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
                    "ClickNick started rebuilding the workspace during the export, so nothing "
                    "was exported. Try again when the build finishes."
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

        Return True if the result was stored. Return False if invalidate() ran or a newer
        build started while this build ran. The result is then dropped. *serves* is the value
        that ``mark_building`` returned for the request that this build serves. By default it
        is every request so far. If more requests were made since, the status stays BUILDING
        for the build that serves them.

        Call it from a background thread. The main thread reads the results that it stores.
        When *persist_dir* is given, the pyrung project is also written to disk.
        *workspace_kind* chooses which lifecycle guidance pyrung writes into the generated
        docs.

        If the pipeline raises, the status becomes FAILED and the reason is recorded, unless
        a newer build or request has taken over. Either way, the exception is raised again.
        The UI can explain the failure even if the caller swallows the exception. Any previous
        good result is kept, so a failed *rebuild* does not take working analysis away from
        open windows.
        """
        with self._lock:
            # Readers compare this counter before and after their work to learn whether a
            # rebuild ran meanwhile.
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
            dataview, program, project_dir, (tag_to_key, key_to_tag) = _build_graph(
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
                dataview=dataview,
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
        """Return the tag names that are both in the program's DataView and in the addr_key map."""
        if self._result is None:
            return frozenset()
        return frozenset(self._result.dataview.tags) & frozenset(self._result.tag_to_addr_key)

    def get_role_keys(self, role: str) -> set[int]:
        """Return addr_keys for tags with the given role.

        role is one of: "input", "output" (terminals), "pivot", "isolated".
        """
        if self._result is None:
            return set()

        cached = self._result.role_cache.get(role)
        if cached is not None:
            return cached

        dataview = self._result.dataview
        role_views = {
            "input": dataview.inputs,
            "output": dataview.terminals,
            "pivot": dataview.pivots,
            "isolated": dataview.isolated,
        }
        role_view = role_views.get(role)
        if role_view is None:
            return set()

        keys = self._addr_keys(role_view().tags)

        self._result.role_cache[role] = keys
        return keys

    def get_upstream_keys(self, tag_name: str) -> set[int]:
        """Return the addr_keys of the tags in pyrung's ``DataView.upstream()`` of *tag_name*.

        For a tag that a subroutine writes, the cone stops at the conditions of the rungs that
        call the subroutine.
        """
        if self._result is None:
            return set()
        return self._addr_keys(self._result.dataview.upstream(tag_name).tags)

    def get_downstream_keys(self, tag_name: str) -> set[int]:
        """Return the addr_keys of the tags in pyrung's ``DataView.downstream()`` of *tag_name*.

        If *tag_name* is in the condition of a rung that calls a subroutine, the cone includes
        every tag that the subroutine writes.
        """
        if self._result is None:
            return set()
        return self._addr_keys(self._result.dataview.downstream(tag_name).tags)

    def _addr_keys(self, tag_names: Iterable[str]) -> set[int]:
        """Return the addr_keys of the names in *tag_names* that the addr_key map holds."""
        assert self._result is not None
        tag_to_addr_key = self._result.tag_to_addr_key
        return {tag_to_addr_key[name] for name in tag_names if name in tag_to_addr_key}

    def run_validation(self) -> ValidationReport | None:
        if self._result is None:
            return None
        from pyrung.validation import CheckConfig, load_check_config

        if self.check_selection is not None:
            config = self.check_selection.load()
            if self.project_dir is not None:
                self.check_selection.sync(self.project_dir)
        else:
            config = (
                load_check_config(self.project_dir / "pyproject.toml") if self.project_dir else None
            ) or CheckConfig()
        return self._result.program.check(select=set(config.resolve()))
