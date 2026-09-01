"""Client helper: connect to a running LiveServer and send one command."""

from __future__ import annotations

from multiprocessing.connection import Client

from .session import resolve_address


def send_command(label: str | None, command: str) -> tuple[bool, str]:
    """Connect to session *label* (or the sole active one), send *command*.

    Returns ``(ok, text)``; ``ok`` is False when the server replied with an
    ``ERROR: `` prefix. Raises ``FileNotFoundError``/``LookupError`` from
    :func:`resolve_address` when no single session can be selected.
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
