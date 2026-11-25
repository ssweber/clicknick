"""Read where the workspace's program stops, from the ``src/plc`` that pyrung loads.

The workspace holds pyrung's ``undecoded()`` marker in place of a rung that ClickNick cannot
read from CLICK. pyrung leaves out every rung after the marker. The user can edit ``src/plc``,
so the Simulator reads the markers from the source that it launches or writes, not from the
analysis build of CLICK's save. Like ``program_check``, a process of its own imports the
source, so that the app never imports the workspace's code.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .project_workspace import NO_WINDOW, headless_python, project_environment

if TYPE_CHECKING:
    from .analysis_service import UndecodedRung

#: How long the worker may take, in seconds, before the read fails
READ_TIMEOUT = 60


def read_program_stops(project_dir: Path) -> tuple[UndecodedRung, ...]:
    """Return the CLICK rungs that ``undecoded()`` markers stand in for in *project_dir*'s source.

    Return an empty tuple if the workspace has no ``src/plc/main.py``. Raise ``ValueError``
    if the worker fails or takes longer than :data:`READ_TIMEOUT`. The error text is the
    last line of the worker's error output.
    """
    from .analysis_service import UndecodedRung

    if not (project_dir / "src" / "plc" / "main.py").is_file():
        return ()
    with tempfile.TemporaryDirectory(prefix="clicknick-stops-", ignore_cleanup_errors=True) as tmp:
        # The worker writes its answer to a file, because the source may print to stdout
        answer = Path(tmp) / "stops.json"
        try:
            result = subprocess.run(
                [
                    headless_python(),
                    "-m",
                    "clicknick.services.program_stops",
                    "--worker",
                    str(answer),
                ],
                cwd=str(project_dir),
                env=project_environment(project_dir),
                creationflags=NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=READ_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise ValueError(f"reading src/plc took longer than {READ_TIMEOUT} seconds.") from None
        if result.returncode != 0:
            lines = result.stderr.strip().splitlines()
            raise ValueError(
                lines[-1] if lines else f"the worker exited with code {result.returncode}."
            )
        try:
            pairs = json.loads(answer.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ValueError("the source ended the worker before it could answer.") from None
    return tuple(UndecodedRung(program, rung) for program, rung in pairs)


def _worker(answer: Path) -> None:
    """Import the workspace's ``plc.main`` and write its markers to *answer* as JSON."""
    from plc.main import logic
    from pyrung import Program

    from .analysis_service import undecoded_rungs_in

    if not isinstance(logic, Program):
        raise TypeError(
            "src/plc/main.py must define logic as a pyrung Program. It defines a "
            f"{type(logic).__name__}."
        )
    pairs = [[rung.program, rung.rung] for rung in undecoded_rungs_in(logic)]
    answer.write_text(json.dumps(pairs), encoding="utf-8")


if __name__ == "__main__":
    _worker(Path(sys.argv[2]))
