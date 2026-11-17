"""Paths and subprocess environment for a generated pyrung project."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

PLC_PACKAGE_PATH = Path("src") / "plc"
PLC_BACKUP_PATH = Path("backup") / PLC_PACKAGE_PATH
GENERATED_SOURCE_STATE_PATH = Path("backup") / "generated-source.json"
# This file records when the backup in backup/src/plc was taken. An older backup has its time
# in its folder name instead.
PLC_BACKUP_TIME_PATH = Path("backup") / "backup-time.txt"
OLDER_PLC_BACKUPS_PATH = Path("backup") / "older"
#: How many backups ClickNick keeps, counting backup/src/plc and the older ones.
KEPT_PLC_BACKUPS = 5
# Older backups are named by their time in UTC. Local time can go back at a daylight-saving or
# time-zone change, and the names would then sort in the wrong order.
_OLDER_NAME_FORMAT = "%Y%m%dT%H%M%SZ"
_OLDER_NAME = re.compile(r"(\d{8}T\d{6}Z)(?:-(\d+))?")
_PRUNING_PREFIX = ".pruning-"
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")
# workspace_writing keeps one lock here for each workspace folder.
_WORKSPACE_LOCKS: dict[str, threading.RLock] = {}
_WORKSPACE_LOCKS_GUARD = threading.Lock()


class WorkspaceBusyError(ValueError):
    """Raised when a build is regenerating the workspace *where*, a folder or words naming one."""

    def __init__(self, where: Path | str) -> None:
        super().__init__(f"ClickNick is rebuilding {where} from CLICK. Try again when it finishes.")


@contextmanager
def workspace_writing(project_dir: Path, *, wait: bool = False) -> Iterator[None]:
    """Hold *project_dir*'s lock while the caller reads or writes its ``src/plc`` and backups.

    Four tasks hold the lock: a build while it copies its output into the workspace, a backup,
    a restore, and choosing a workspace. None of them can see a tree that another has only
    half written. The build runs on a worker thread and waits for the lock (``wait=True``).
    The others run on the Tk thread. If the lock is taken, they raise WorkspaceBusyError
    instead of freezing the window until the build ends. The thread that holds the lock may
    take it again.
    """
    key = os.path.normcase(str(project_dir.resolve()))
    with _WORKSPACE_LOCKS_GUARD:
        lock = _WORKSPACE_LOCKS.setdefault(key, threading.RLock())
    if not lock.acquire(blocking=wait):
        raise WorkspaceBusyError(project_dir)
    try:
        yield
    finally:
        lock.release()


def plc_source_dir(project_dir: Path) -> Path:
    """Return the generated import package inside a project root."""
    return project_dir / PLC_PACKAGE_PATH


def plc_backup_dir(project_dir: Path) -> Path:
    """Return the recovery snapshot path inside a generated project."""
    return project_dir / PLC_BACKUP_PATH


def older_plc_backups_dir(project_dir: Path) -> Path:
    """Return the folder of the older backups, each ``<YYYYMMDD-HHMMSS>/src/plc``."""
    return project_dir / OLDER_PLC_BACKUPS_PATH


def generated_source_state_path(project_dir: Path) -> Path:
    """Return the path of the record of the last source generated from CLICK."""
    return project_dir / GENERATED_SOURCE_STATE_PATH


def _source_fingerprint(source: Path) -> dict[str, str]:
    """Return a SHA-256 hash of each file in *source*, keyed by its path in *source*.

    ``__pycache__`` folders and ``.pyc`` files are left out.
    """
    fingerprint: dict[str, str] = {}
    if not source.is_dir():
        return fingerprint

    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint[path.relative_to(source).as_posix()] = digest.hexdigest()
    return fingerprint


def _file_digest(path: Path) -> str | None:
    """Return *path*'s content hash, or None when it cannot be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _source_stamp(source: Path) -> tuple[tuple[str, int, int], ...]:
    """Return the path, size and modification time of each file in *source*.

    ``__pycache__`` folders and ``.pyc`` files are left out. This is cheap to compute, and
    any edit changes it.
    """
    if not source.is_dir():
        return ()
    stamp: list[tuple[str, int, int]] = []
    for path in sorted(source.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        try:
            if not path.is_file():
                continue
            info = path.stat()
        except OSError:
            continue
        stamp.append((path.relative_to(source).as_posix(), info.st_size, info.st_mtime_ns))
    return tuple(stamp)


class PlcSourceWatch:
    """Tells whether a project's ``src/plc`` still holds what it held when the watch began.

    Each check reads only file sizes and times. It hashes the files again only when a size
    or time changed. An edit that you undo in an editor, or a file that you save unchanged,
    therefore does not count.
    """

    def __init__(self, project_dir: Path) -> None:
        self._source = plc_source_dir(project_dir)
        self._run_py = project_dir / "run.py"
        self._stamp = _source_stamp(self._source)
        self._fingerprint: dict[str, str] | None
        try:
            self._fingerprint = _source_fingerprint(self._source)
        except OSError:
            # A file could not be read. changed() then never reports a change, and same()
            # always returns False.
            self._fingerprint = None
        self._run_digest = _file_digest(self._run_py)
        self._changed = False

    def same(self) -> bool:
        """Return True only when ``src/plc`` and ``run.py`` read the same as when the watch began.

        Together they are the program that pyrung runs. If a file could not be read at either
        time, this returns False, because nothing proves that the program is the same.
        :meth:`changed` differs here. It reports no change for such a file.
        """
        if self._fingerprint is None or self._run_digest is None:
            return False
        if _file_digest(self._run_py) != self._run_digest:
            return False
        stamp = _source_stamp(self._source)
        if stamp == self._stamp:
            return not self._changed  # Nothing changed since the last check, so its answer stands
        try:
            current = _source_fingerprint(self._source)
        except OSError:
            return False
        self._stamp = stamp
        self._changed = current != self._fingerprint
        return not self._changed

    def changed(self) -> bool:
        stamp = _source_stamp(self._source)
        if self._fingerprint is None or stamp == self._stamp:
            return self._changed
        try:
            self._changed = _source_fingerprint(self._source) != self._fingerprint
        except OSError:
            # A file could not be read, perhaps because it is being written. The next check
            # reads it again.
            return self._changed
        self._stamp = stamp
        return self._changed


def plc_source_is_modified(project_dir: Path) -> bool:
    """Return whether ``src/plc`` differs from the source that ClickNick last generated from CLICK.

    If ``src/plc`` exists but no generation was recorded, or the record cannot be read, the
    source counts as modified. That is the cautious choice. ClickNick then backs up the
    source before the first build overwrites it.
    """
    source = plc_source_dir(project_dir)
    if not source.is_dir():
        return False

    state_path = generated_source_state_path(project_dir)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        recorded = state["files"]
        if not isinstance(recorded, dict):
            return True
    except (OSError, KeyError, TypeError, ValueError):
        return True
    return _source_fingerprint(source) != recorded


def record_generated_plc_source(project_dir: Path) -> Path:
    """Record ``src/plc`` as unedited source generated from CLICK, and return the record's path."""
    source = plc_source_dir(project_dir)
    if not source.is_dir():
        raise ValueError(f"generated source directory not found: {source}")

    state_path = generated_source_state_path(project_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    staging = state_path.with_suffix(f"{state_path.suffix}.staging")
    payload = {"version": 1, "files": _source_fingerprint(source)}
    staging.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    staging.replace(state_path)
    return state_path


def _replace_trees(pairs: Sequence[tuple[Path, Path]]) -> None:
    """Copy each source over its destination. Either every destination changes, or none does.

    Each copy is staged beside its destination first. The old trees then move aside and the
    new ones move in. If any rename fails, the new trees come out and the old ones go back.
    """
    moves: list[tuple[Path, Path, Path]] = []
    for source, destination in pairs:
        if not source.is_dir():
            raise ValueError(f"source directory not found: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        moves.append(
            (
                destination.parent / f".{destination.name}.staging",
                destination,
                destination.parent / f".{destination.name}.previous",
            )
        )
    for staging, _destination, previous in moves:
        for leftover in (staging, previous):
            if leftover.exists():
                shutil.rmtree(leftover)

    swapped: list[tuple[Path, Path, Path, bool, bool]] = []
    try:
        for (source, _), (staging, _destination, _previous) in zip(pairs, moves, strict=True):
            shutil.copytree(source, staging, ignore=_COPY_IGNORE)
        try:
            for staging, destination, previous in moves:
                aside = placed = False
                try:
                    if destination.exists():
                        destination.replace(previous)
                        aside = True
                    staging.replace(destination)
                    placed = True
                finally:
                    swapped.append((staging, destination, previous, aside, placed))
        except Exception:
            for staging, destination, previous, aside, placed in reversed(swapped):
                try:
                    if placed:
                        destination.replace(staging)
                    if aside:
                        previous.replace(destination)
                except OSError:
                    pass
            raise
        for _staging, _destination, previous in moves:
            shutil.rmtree(previous, ignore_errors=True)
    finally:
        for staging, _destination, _previous in moves:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


def _file_count(root: Path) -> int:
    return sum(path.is_file() for path in root.rglob("*"))


def _replace_tree(source: Path, destination: Path) -> int:
    """Copy *source* over *destination* and return the number of files in *destination*.

    No reader of *destination* sees the new tree half copied.
    """
    _replace_trees([(source, destination)])
    return _file_count(destination)


def _now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _latest_mtime(root: Path) -> dt.datetime | None:
    try:
        timestamps = [path.stat().st_mtime for path in root.rglob("*") if path.is_file()]
    except OSError:
        return None
    if not timestamps:
        return None
    return dt.datetime.fromtimestamp(max(timestamps)).astimezone()


def plc_backup_time(project_dir: Path) -> dt.datetime | None:
    """Return when the backup in ``backup/src/plc`` was taken, or None without a backup.

    Some backups have no recorded time. They come from an earlier ClickNick, or their time
    could not be written. For those, the time of the backup's newest file is used instead.
    """
    backup = plc_backup_dir(project_dir)
    if not backup.is_dir():
        return None
    try:
        text = (project_dir / PLC_BACKUP_TIME_PATH).read_text(encoding="utf-8").strip()
        return dt.datetime.fromisoformat(text)
    except (OSError, ValueError):
        return _latest_mtime(backup)


def _record_backup_time(project_dir: Path, when: dt.datetime) -> None:
    """Record *when* as the time of the backup in ``backup/src/plc``.

    The backup is already in place, so a failure to record the time does not fail the backup.
    If the time cannot be written, this sets the time of each file in the backup to *when*.
    ``plc_backup_time`` then reads *when* from the newest file. The files' own times can be
    much older, because a copy keeps each file's time, and a backup that was promoted from
    an older one keeps that backup's files.
    """
    path = project_dir / PLC_BACKUP_TIME_PATH
    staging = path.with_suffix(f"{path.suffix}.staging")
    try:
        staging.write_text(when.isoformat(timespec="seconds") + "\n", encoding="utf-8")
        staging.replace(path)
    except OSError:
        # Delete the old time file. It holds the previous backup's time, and
        # plc_backup_time would give that time to this backup.
        for leftover in (staging, path):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass
        stamp = when.timestamp()
        for file in plc_backup_dir(project_dir).rglob("*"):
            try:
                if file.is_file():
                    os.utime(file, (stamp, stamp))
            except OSError:
                pass


def older_plc_backup_time(name: str) -> dt.datetime:
    """Return when the older backup *name* (one of ``older_plc_backups``) was taken, in UTC."""
    match = _OLDER_NAME.fullmatch(name)
    if match is None:
        raise ValueError(f"not an older backup name: {name!r}")
    return dt.datetime.strptime(match.group(1), _OLDER_NAME_FORMAT).replace(tzinfo=dt.UTC)


def older_plc_backups(project_dir: Path) -> list[str]:
    """Return the names of the older backups, newest first.

    A second backup in the same second gets ``-2``, ``-3`` and so on after its time.
    Folders named otherwise are not backups and are left alone.
    """
    root = older_plc_backups_dir(project_dir)
    if not root.is_dir():
        return []
    slots: list[tuple[tuple[str, int], str]] = []
    for path in root.iterdir():
        match = _OLDER_NAME.fullmatch(path.name)
        if match and (path / PLC_PACKAGE_PATH).is_dir():
            slots.append(((match.group(1), int(match.group(2) or 1)), path.name))
    return [name for _key, name in sorted(slots, reverse=True)]


def _retire_newest_backup(project_dir: Path) -> Path:
    """Move ``backup/src/plc`` to a new folder in ``backup/older`` and return that folder.

    The folder is named by the backup's time.
    """
    when = plc_backup_time(project_dir) or _now()
    root = older_plc_backups_dir(project_dir)
    base = when.astimezone(dt.UTC).strftime(_OLDER_NAME_FORMAT)
    # One past the highest suffix in use for this second, so the newest sorts first.
    taken = [
        int(match.group(2) or 1)
        for path in (root.iterdir() if root.is_dir() else ())
        if (match := _OLDER_NAME.fullmatch(path.name)) and match.group(1) == base
    ]
    suffix = max(taken, default=0) + 1
    slot = root / (base if suffix == 1 else f"{base}-{suffix}")
    (slot / PLC_PACKAGE_PATH).parent.mkdir(parents=True)
    try:
        plc_backup_dir(project_dir).replace(slot / PLC_PACKAGE_PATH)
    except OSError:
        shutil.rmtree(slot, ignore_errors=True)
        raise
    return slot


def _prune_older_backups(project_dir: Path, *, keep: str | None = None) -> None:
    """Delete the oldest backups beyond ``KEPT_PLC_BACKUPS``, never the older backup *keep*.

    Callers prune once, after the whole operation succeeded. The older backup *keep* stays
    even when it is beyond the limit. There are then six backups for a while, and the next
    backup trims them to five. Before it deletes a backup, this function renames it so that
    ``older_plc_backups`` does not list it. If a delete stops part way, no broken backup is
    left for a restore to use.
    """
    root = older_plc_backups_dir(project_dir)
    if not root.is_dir():
        return
    for leftover in root.glob(f"{_PRUNING_PREFIX}*"):
        shutil.rmtree(leftover, ignore_errors=True)
    names = [name for name in older_plc_backups(project_dir) if name != keep]
    for name in names[KEPT_PLC_BACKUPS - 1 :]:
        doomed = root / f"{_PRUNING_PREFIX}{name}"
        try:
            (root / name).replace(doomed)
        except OSError:
            continue  # The backup is still whole. The next backup tries again.
        shutil.rmtree(doomed, ignore_errors=True)


def _promote_older_backup(project_dir: Path, name: str) -> Path | None:
    """Make the older backup *name* the newest.

    Return the folder that the previous newest backup moved to, or None if there was none.
    """
    newest = plc_backup_dir(project_dir)
    slot = older_plc_backups_dir(project_dir) / name
    retired = _retire_newest_backup(project_dir) if newest.exists() else None
    try:
        (slot / PLC_PACKAGE_PATH).replace(newest)
    except OSError:
        if retired is not None and not newest.exists():
            (retired / PLC_PACKAGE_PATH).replace(newest)
            shutil.rmtree(retired, ignore_errors=True)
        raise
    shutil.rmtree(slot, ignore_errors=True)  # Its src/plc has moved out, so the slot is empty
    return retired


def _back_up(project_dir: Path) -> tuple[int, Path | None]:
    """Make ``src/plc`` the newest backup, without pruning.

    Return the backup's file count and the folder in ``backup/older`` that the previous
    newest backup moved to. That folder is None if no backup moved.

    If a kept backup already holds the same tree, no new backup is made. If that backup is
    the newest, it only gets a new time. If it is an older one, it becomes the newest.
    """
    source = plc_source_dir(project_dir)
    if not source.is_dir():
        raise ValueError(f"{source} does not exist, so there is nothing to back up.")
    destination = plc_backup_dir(project_dir)
    when = _now()
    fingerprint = _source_fingerprint(source)
    if destination.is_dir() and _source_fingerprint(destination) == fingerprint:
        _record_backup_time(project_dir, when)
        return _file_count(destination), None
    root = older_plc_backups_dir(project_dir)
    for name in older_plc_backups(project_dir):
        if _source_fingerprint(root / name / PLC_PACKAGE_PATH) == fingerprint:
            retired = _promote_older_backup(project_dir, name)
            _record_backup_time(project_dir, when)
            return _file_count(destination), retired

    retired = _retire_newest_backup(project_dir) if destination.exists() else None
    try:
        file_count = _replace_tree(source, destination)
    except Exception:
        if retired is not None and not destination.exists():
            (retired / PLC_PACKAGE_PATH).replace(destination)
            shutil.rmtree(retired, ignore_errors=True)
        raise
    _record_backup_time(project_dir, when)
    return file_count, retired


def backup_plc_source(project_dir: Path) -> tuple[Path, int]:
    """Copy the active ``src/plc`` tree to ``backup/src/plc``, keeping the backups before it.

    The backup that this one replaces moves to ``backup/older/<YYYYMMDDTHHMMSSZ>/src/plc``,
    where the name is the UTC time it was taken. The oldest backups are deleted, so that
    ``KEPT_PLC_BACKUPS`` are kept in all. If a kept backup already holds the same tree, no
    new backup is made. That backup becomes the newest, with a new time.
    """
    with workspace_writing(project_dir):
        file_count, _retired = _back_up(project_dir)
        _prune_older_backups(project_dir)
    return plc_backup_dir(project_dir), file_count


def backup_modified_plc_source(project_dir: Path) -> tuple[Path, int] | None:
    """Back up ``src/plc`` only if it holds edits that were not generated from CLICK.

    Return what ``backup_plc_source`` returns, or None if there was nothing to back up.
    """
    with workspace_writing(project_dir):
        if not plc_source_is_modified(project_dir):
            return None
        return backup_plc_source(project_dir)


@dataclass(frozen=True)
class PlcRestore:
    """What ``restore_plc_source`` did."""

    #: Where the restored backup is kept after the restore. A backup of the edits moves the
    #: newest backup from ``backup/src/plc`` to a folder in ``backup/older``.
    restored_from: Path
    file_count: int
    #: True if ``src/plc`` held edits that differ from the restored backup. Those edits
    #: became the newest backup.
    edits_backed_up: bool


def _restore(project_dir: Path, older: str | None) -> PlcRestore:
    if older is None:
        chosen = plc_backup_dir(project_dir)
        if not chosen.is_dir():
            raise ValueError("There is no backup of src/plc yet. Run 'clicknick-cli backup' first.")
    else:
        names = older_plc_backups(project_dir)
        if older not in names:
            listed = ", ".join(names) if names else "none"
            raise ValueError(f"no older backup named {older!r}. Older backups: {listed}")
        chosen = older_plc_backups_dir(project_dir) / older / PLC_PACKAGE_PATH
    destination = plc_source_dir(project_dir)
    with tempfile.TemporaryDirectory(
        prefix=".restoring-", dir=project_dir / "backup", ignore_cleanup_errors=True
    ) as staging_root:
        staged = Path(staging_root) / "plc"
        shutil.copytree(chosen, staged, ignore=_COPY_IGNORE)
        backed_up, retired = False, None
        if (
            destination.is_dir()
            and plc_source_is_modified(project_dir)
            and _source_fingerprint(destination) != _source_fingerprint(staged)
        ):
            _count, retired = _back_up(project_dir)
            backed_up = True
        file_count = _replace_tree(staged, destination)
    if older is None and retired is not None:
        chosen = retired / PLC_PACKAGE_PATH
        older = retired.name
    _prune_older_backups(project_dir, keep=older)
    return PlcRestore(chosen, file_count, backed_up)


def restore_plc_source(project_dir: Path, older: str | None = None) -> PlcRestore:
    """Replace active ``src/plc`` with the newest backup, or the older one named *older*.

    First, edits in ``src/plc`` that match neither the last generation nor the chosen backup
    become the newest backup, as in ``backup_modified_plc_source``. That backup moves
    ``backup/src/plc`` into ``backup/older``, so this function copies the chosen backup to a
    staging folder before it backs up the edits. It prunes old backups only after ``src/plc``
    holds the restored tree, and it never prunes the chosen backup.
    """
    with workspace_writing(project_dir):
        return _restore(project_dir, older)


#: The creation flag that starts ClickNick's Python child processes without a console window.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def headless_python() -> str:
    """Return the interpreter for ClickNick's own Python children (the simulation, checks, exports).

    When the ``clicknick`` GUI launcher starts ClickNick, ``sys.executable`` is the venv's
    pythonw.exe. That is a stub that starts the real interpreter as a second process.
    Windows shows its busy cursor for that GUI start until a window appears, and no window
    ever appears. The console python.exe, started with ``NO_WINDOW``, shows neither a window
    nor the busy cursor.
    """
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(exe)


def project_environment(project_dir: Path) -> dict[str, str]:
    """Return a copy of the environment with the project's ``src`` folder first on PYTHONPATH.

    ClickNick's child processes run with it so that they can import the generated package.
    """
    env = os.environ.copy()
    src_dir = str(project_dir / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join((src_dir, existing)) if existing else src_dir
    return env
