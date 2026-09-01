"""Paths and subprocess environment for a generated pyrung project."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

PLC_PACKAGE_PATH = Path("src") / "plc"
PLC_BACKUP_PATH = Path("backup") / PLC_PACKAGE_PATH
GENERATED_SOURCE_STATE_PATH = Path("backup") / "generated-source.json"
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def plc_source_dir(project_dir: Path) -> Path:
    """Return the generated import package inside a project root."""
    return project_dir / PLC_PACKAGE_PATH


def plc_backup_dir(project_dir: Path) -> Path:
    """Return the recovery snapshot path inside a generated project."""
    return project_dir / PLC_BACKUP_PATH


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


def _replace_tree(source: Path, destination: Path) -> int:
    """Copy *source* over *destination* without exposing a partial new tree."""
    if not source.is_dir():
        raise ValueError(f"source directory not found: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging"
    previous = destination.parent / f".{destination.name}.previous"
    if staging.exists():
        shutil.rmtree(staging)
    if previous.exists():
        shutil.rmtree(previous)

    try:
        shutil.copytree(source, staging, ignore=_COPY_IGNORE)
        if destination.exists():
            destination.replace(previous)
        try:
            staging.replace(destination)
        except Exception:
            if previous.exists() and not destination.exists():
                previous.replace(destination)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    return sum(path.is_file() for path in destination.rglob("*"))


def backup_plc_source(project_dir: Path) -> tuple[Path, int]:
    """Replace the recovery snapshot with the active ``src/plc`` tree."""
    source = plc_source_dir(project_dir)
    if not source.is_dir():
        raise ValueError(f"generated source directory not found: {source}")
    destination = plc_backup_dir(project_dir)
    return destination, _replace_tree(source, destination)


def backup_modified_plc_source(project_dir: Path) -> tuple[Path, int] | None:
    """Snapshot active source only when it contains work beyond regeneration."""
    if not plc_source_is_modified(project_dir):
        return None
    return backup_plc_source(project_dir)


def restore_plc_source(project_dir: Path) -> tuple[Path, int]:
    """Replace active ``src/plc`` with the recovery snapshot."""
    source = plc_backup_dir(project_dir)
    if not source.is_dir():
        raise ValueError("no source backup found; run 'clicknick-cli backup' first")
    destination = plc_source_dir(project_dir)
    return source, _replace_tree(source, destination)


def project_environment(project_dir: Path) -> dict[str, str]:
    """Expose the generated src layout to ClickNick-owned subprocesses."""
    env = os.environ.copy()
    src_dir = str(project_dir / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join((src_dir, existing)) if existing else src_dir
    return env
