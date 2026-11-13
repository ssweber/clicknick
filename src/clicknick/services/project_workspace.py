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
from collections.abc import Sequence
from pathlib import Path

PLC_PACKAGE_PATH = Path("src") / "plc"
PLC_BACKUP_PATH = Path("backup") / PLC_PACKAGE_PATH
GENERATED_SOURCE_STATE_PATH = Path("backup") / "generated-source.json"
# When the backup in backup/src/plc was taken; older ones carry it in their folder name.
PLC_BACKUP_TIME_PATH = Path("backup") / "backup-time.txt"
OLDER_PLC_BACKUPS_PATH = Path("backup") / "older"
#: Backups kept in all: backup/src/plc and the older ones.
KEPT_PLC_BACKUPS = 5
_OLDER_NAME_FORMAT = "%Y%m%d-%H%M%S"
_OLDER_NAME = re.compile(r"(\d{8}-\d{6})(?:-(\d+))?")
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


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
    """Return the recorded state of the last source generated from CLICK."""
    return project_dir / GENERATED_SOURCE_STATE_PATH


def _source_fingerprint(source: Path) -> dict[str, str]:
    """Return stable content hashes for the meaningful files in *source*."""
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


def _source_stamp(source: Path) -> tuple[tuple[str, int, int], ...]:
    """Each meaningful file's path, size and modification time: cheap, and moved by any edit."""
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

    Each check reads only file sizes and times; the files are hashed again
    only when one of those moved, so an edit undone in an editor, or a file
    saved unchanged, does not count.
    """

    def __init__(self, project_dir: Path) -> None:
        self._source = plc_source_dir(project_dir)
        self._stamp = _source_stamp(self._source)
        self._fingerprint: dict[str, str] | None
        try:
            self._fingerprint = _source_fingerprint(self._source)
        except OSError:
            self._fingerprint = None  # unreadable: never reported as changed
        self._changed = False

    def changed(self) -> bool:
        stamp = _source_stamp(self._source)
        if self._fingerprint is None or stamp == self._stamp:
            return self._changed
        try:
            self._changed = _source_fingerprint(self._source) != self._fingerprint
        except OSError:
            return self._changed  # a file being written: the next check reads it again
        self._stamp = stamp
        return self._changed


def plc_source_is_modified(project_dir: Path) -> bool:
    """Return whether active source differs from the last CLICK generation.

    A pre-existing project without recorded state is treated conservatively as
    modified so its source is snapshotted before the first protected rebuild.
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
    """Record active source as the clean result of a CLICK regeneration."""
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
    """Copy each source over its destination: every destination changes, or none does.

    Each copy is staged beside its destination first. The old trees then move
    aside and the new ones in; if any rename fails, the new trees come out and
    the old ones go back.
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
    """Copy *source* over *destination* without exposing a partial new tree."""
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
    """When the backup in ``backup/src/plc`` was taken, or None without one.

    A backup from an earlier ClickNick has no recorded time: its newest file's
    time stands in.
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
    """Record *when*; a backup is in place either way, so a failure here never fails it."""
    path = project_dir / PLC_BACKUP_TIME_PATH
    staging = path.with_suffix(f"{path.suffix}.staging")
    try:
        staging.write_text(when.isoformat(timespec="seconds") + "\n", encoding="utf-8")
        staging.replace(path)
    except OSError:
        # The time of the backup before would misname this one: its files' time stands in.
        for leftover in (staging, path):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass


def older_plc_backups(project_dir: Path) -> list[str]:
    """The names of the older backups, newest first.

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
    """Move ``backup/src/plc`` to a new older slot named by its time; return the slot."""
    when = plc_backup_time(project_dir) or _now()
    root = older_plc_backups_dir(project_dir)
    base = when.strftime(_OLDER_NAME_FORMAT)
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


def _prune_older_backups(project_dir: Path) -> None:
    root = older_plc_backups_dir(project_dir)
    for name in older_plc_backups(project_dir)[KEPT_PLC_BACKUPS - 1 :]:
        shutil.rmtree(root / name, ignore_errors=True)


def backup_plc_source(project_dir: Path) -> tuple[Path, int]:
    """Copy the active ``src/plc`` tree to ``backup/src/plc``, keeping the backups before it.

    The backup it replaces moves to ``backup/older/<YYYYMMDD-HHMMSS>/src/plc``
    (the time it was taken), and the oldest go so that ``KEPT_PLC_BACKUPS`` are
    kept in all. A tree that matches the newest backup makes no new one; only
    its time moves.
    """
    source = plc_source_dir(project_dir)
    if not source.is_dir():
        raise ValueError(f"generated source directory not found: {source}")
    destination = plc_backup_dir(project_dir)
    when = _now()
    if destination.is_dir() and _source_fingerprint(destination) == _source_fingerprint(source):
        _record_backup_time(project_dir, when)
        return destination, _file_count(destination)

    slot = _retire_newest_backup(project_dir) if destination.exists() else None
    try:
        file_count = _replace_tree(source, destination)
    except Exception:
        if slot is not None and not destination.exists():
            (slot / PLC_PACKAGE_PATH).replace(destination)
            shutil.rmtree(slot, ignore_errors=True)
        raise
    _record_backup_time(project_dir, when)
    _prune_older_backups(project_dir)
    return destination, file_count


def backup_modified_plc_source(project_dir: Path) -> tuple[Path, int] | None:
    """Snapshot active source only when it contains work beyond regeneration."""
    if not plc_source_is_modified(project_dir):
        return None
    return backup_plc_source(project_dir)


def restore_plc_source(project_dir: Path, older: str | None = None) -> tuple[Path, int]:
    """Replace active ``src/plc`` with the newest backup, or the older one named *older*."""
    if older is None:
        source = plc_backup_dir(project_dir)
        if not source.is_dir():
            raise ValueError("no source backup found; run 'clicknick-cli backup' first")
    else:
        names = older_plc_backups(project_dir)
        if older not in names:
            listed = ", ".join(names) if names else "none"
            raise ValueError(f"no older backup named {older!r}; older backups: {listed}")
        source = older_plc_backups_dir(project_dir) / older / PLC_PACKAGE_PATH
    destination = plc_source_dir(project_dir)
    return source, _replace_tree(source, destination)


#: Creation flags for ClickNick's Python children: no console window.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def headless_python() -> str:
    """The interpreter for ClickNick's own Python children (the simulation, checks, exports).

    Started from the ``clicknick`` GUI launcher, ``sys.executable`` is the venv's
    pythonw.exe: a stub that starts the real interpreter as a second process, and
    Windows shows its busy cursor for that GUI start until a window appears, which
    never happens. The console python.exe, started with ``NO_WINDOW``, shows
    neither a window nor the busy cursor.
    """
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(exe)


def project_environment(project_dir: Path) -> dict[str, str]:
    """Expose the generated src layout to ClickNick-owned subprocesses."""
    env = os.environ.copy()
    src_dir = str(project_dir / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join((src_dir, existing)) if existing else src_dir
    return env
