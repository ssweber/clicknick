"""Paths and subprocess environment for a generated pyrung project."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

PLC_PACKAGE_PATH = Path("src") / "plc"
PLC_BACKUP_PATH = Path("backup") / PLC_PACKAGE_PATH
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def plc_source_dir(project_dir: Path) -> Path:
    """Return the generated import package inside a project root."""
    return project_dir / PLC_PACKAGE_PATH


def plc_backup_dir(project_dir: Path) -> Path:
    """Return the recovery snapshot path inside a generated project."""
    return project_dir / PLC_BACKUP_PATH


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
