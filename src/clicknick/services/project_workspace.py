"""Paths and subprocess environment for a generated pyrung project."""

from __future__ import annotations

import os
from pathlib import Path

PLC_PACKAGE_PATH = Path("src") / "plc"


def plc_source_dir(project_dir: Path) -> Path:
    """Return the generated import package inside a project root."""
    return project_dir / PLC_PACKAGE_PATH


def project_environment(project_dir: Path) -> dict[str, str]:
    """Expose the generated src layout to ClickNick-owned subprocesses."""
    env = os.environ.copy()
    src_dir = str(project_dir / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join((src_dir, existing)) if existing else src_dir
    return env
