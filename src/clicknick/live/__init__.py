"""Out-of-process live editing for a running ClickNick app.

A small request/response IPC (modeled on ``pyrung live``) that lets an
external process — a CLI, or an LLM tool — push edits into a *running*
ClickNick instance. Edits flow through the same ``AddressStore.edit_session``
path the UI uses, so they appear as ordinary unsaved (dirty) changes,
undoable with Ctrl+Z, whether or not the Address Editor is open.

Architecture
------------
- ``LiveServer`` (server side) runs inside the GUI process. A background
  daemon thread accepts localhost connections; received commands are
  marshaled onto the Tk main thread via a ``queue.Queue`` drained by a
  periodic ``root.after`` poll. This is required because tkinter is
  single-threaded: the socket thread must never touch widgets directly.
- ``client``/``cli`` (client side) is the ``clicknick-live`` command. It
  reads the port file, connects, sends one command, prints the reply.

Session discovery uses port files in a well-known directory:
``<tempdir>/clicknick/clicknick-<name>.port`` holding the TCP port.
"""

from __future__ import annotations

from .server import LiveServer

__all__ = ["LiveServer"]
