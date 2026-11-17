"""Optional Jet access to a project's MDB, through the 32-bit PowerShell that Windows has.

ClickNick uses it when the user chooses the Jet backend, or when no Access ODBC driver is
installed. One PowerShell process runs the requests one at a time, and each runs to the
end. Each request opens and closes its own MDB connection, so no transaction stays open
while the user edits nicknames.
"""

from __future__ import annotations

import atexit
import base64
import json
import os
import queue
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

BACKEND_NAME = "Windows Jet (32-bit PowerShell)"
REQUEST_TIMEOUT = 30.0
SAVE_TIMEOUT = 180.0
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class JetError(RuntimeError):
    """Raised when a Jet database operation fails or cannot be started."""


class JetTransportError(JetError):
    """Raised when the Jet worker times out, exits or sends a response that is not valid.

    If the request was a save, the save may have been committed even though its response was
    lost.
    """


def powershell_path() -> Path:
    return Path(os.environ.get("SystemRoot", "C:/Windows")) / (
        "SysWOW64/WindowsPowerShell/v1.0/powershell.exe"
    )


def is_available() -> bool:
    """Return True on Windows if 32-bit Windows PowerShell exists.

    This check is cheap. Only opening the project's MDB shows that Jet works.
    """
    return os.name == "nt" and powershell_path().is_file()


class JetWorker:
    """Runs one 32-bit PowerShell worker and sends it requests through its pipes.

    The worker starts again for the next request after it exits. Requests and responses
    have a size limit and a timeout. A failed request is not sent again, because a save
    may have been committed.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._responses: queue.Queue = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=10)
        self._serial = 0

    def _stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def _exchange(self, op: str, **payload: Any) -> dict:
        self._serial += 1
        request = (
            json.dumps(
                {"id": self._serial, "op": op, **payload},
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("ascii")
            + b"\n"
        )
        if len(request) > MAX_REQUEST_BYTES:
            raise JetError("Database changes are too large for one save. Save a smaller selection.")
        process, responses = self._process, self._responses

        def send() -> None:
            try:
                process.stdin.write(request)
                process.stdin.flush()
            except (OSError, ValueError) as exc:
                responses.put(exc)

        threading.Thread(target=send, daemon=True).start()
        try:
            line = responses.get(timeout=SAVE_TIMEOUT if op == "save" else REQUEST_TIMEOUT)
            if isinstance(line, Exception):
                raise line
            response = json.loads(line)
            if (
                not isinstance(response, dict)
                or response.get("id") != self._serial
                or not isinstance(response.get("ok"), bool)
                or (response["ok"] and not isinstance(response.get("result"), dict))
            ):
                raise ValueError("Invalid response from the Jet database worker.")
        except (queue.Empty, OSError, ValueError, JetTransportError) as exc:
            detail = "".join(self._stderr)[-2000:]
            self._stop()
            message = "Jet database worker timed out or disconnected."
            if op == "save":
                message += " The save outcome is unknown. Reload the database before retrying."
            if detail:
                message += f" PowerShell: {detail}"
            raise JetTransportError(message) from exc
        if not response["ok"]:
            raise JetError(str(response.get("error", "Jet database operation failed.")))
        return response["result"]

    def _start(self) -> None:
        if not is_available():
            raise JetError("32-bit Windows PowerShell is unavailable on this computer.")
        script = (Path(__file__).parents[1] / "resources" / "jet_sidecar.ps1").read_text(
            encoding="utf-8"
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        argv = [
            str(powershell_path()),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ]
        if len(subprocess.list2cmdline(argv)) >= 32767:
            raise JetError("The Jet worker script exceeds the Windows command-line limit.")
        self._responses = queue.Queue()
        self._stderr = deque(maxlen=10)
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise JetError(f"Could not start the Jet database worker: {exc}") from exc
        self._process = process
        responses, stderr = self._responses, self._stderr

        def read_stdout() -> None:
            try:
                while line := process.stdout.readline(MAX_RESPONSE_BYTES + 1):
                    if len(line) > MAX_RESPONSE_BYTES:
                        responses.put(JetTransportError("Database response is too large."))
                        return
                    responses.put(line)
            except (OSError, ValueError) as exc:
                responses.put(exc)
            finally:
                responses.put(JetTransportError("The Jet database worker exited."))

        def read_stderr() -> None:
            try:
                while chunk := process.stderr.read(1024):
                    stderr.append(chunk.decode("utf-8", errors="replace"))
            except (OSError, ValueError):
                pass

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()
        hello = self._exchange("hello")
        if hello != {"bits": 32, "version": 1}:
            self._stop()
            raise JetTransportError("Unexpected Jet database worker version.")

    def close(self) -> None:
        with self._lock:
            self._stop()

    def request(self, op: str, **payload: Any) -> dict:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._stop()
                try:
                    self._start()
                except Exception:
                    self._stop()
                    raise
            return self._exchange(op, **payload)


_worker = JetWorker()
atexit.register(_worker.close)


class JetConnection:
    """A connection to an MDB that does not keep the file open.

    The worker opens the file for each request and closes it again.
    """

    backend_name = BACKEND_NAME

    def _request(self, op: str, **payload: Any) -> dict:
        if self._closed:
            raise JetError("Database connection is closed.")
        return _worker.request(op, path=self.db_path, **payload)

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(Path(db_path).resolve())
        self._closed = False
        self._request("probe")

    def load_addresses(self) -> list[list]:
        return self._request("read")["rows"]

    def save_addresses(self, deletes: list[int], upserts: list[list]) -> int:
        return self._request("save", deletes=deletes, upserts=upserts)["count"]

    def close(self) -> None:
        self._closed = True
