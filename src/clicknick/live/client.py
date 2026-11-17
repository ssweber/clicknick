"""Client helper: connect to a running LiveServer and send one command."""

from __future__ import annotations

from multiprocessing.connection import Client

from .session import resolve_address


def send_command(label: str | None, command: str) -> tuple[bool, str]:
    """Send *command* to the session named *label* and return the server's reply.

    If *label* is None, the command goes to the only active session.

    Return ``(ok, text)``. ``ok`` is False when the reply starts with ``ERROR: ``, and
    *text* is then the reply without that prefix.

    :func:`resolve_address` raises ``FileNotFoundError`` if no session matches, and
    ``LookupError`` if *label* is None and several sessions are active.
    """
    address = resolve_address(label)
    conn = Client(address, family="AF_INET")
    try:
        conn.send_bytes(command.encode("utf-8"))
        text = conn.recv_bytes().decode("utf-8")
        if text.startswith("ERROR: "):
            return False, text[len("ERROR: ") :]
        return True, text
    finally:
        conn.close()
