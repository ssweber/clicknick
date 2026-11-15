"""The desktop calls the CLICK runner makes (devtools/click_runner.py), and their Win32 version.

The runner drives CLICK only through ``Desktop``, so its logic is tested against a fake
(tests/test_click_runner.py) and this Win32 version stays thin: each method is one or two
Win32 calls with no decisions of its own.

Every ``WM_COMMAND`` goes through ``Desktop.command``, which refuses any command outside
``ALLOWED_COMMANDS``. Read Project and Write Project are not in it, so the runner cannot
read from or write to the PLC.
"""

from __future__ import annotations

import ctypes
import struct
import subprocess
import zlib
from abc import ABC, abstractmethod
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

# CLICK v4's command ids, from CLICK.exe's string table (probe of 2026-11-15)
PASTE = 0xE125  # MFC's ID_EDIT_PASTE
SYNTAX_CHECK = 32846
SAVE_PROJECT = 32898
SAVE_PROJECT_AS = 32899
DISCONNECT = 32850
READ_PROJECT_FROM_PLC = 32853
WRITE_PROJECT_INTO_PLC = 32854

ALLOWED_COMMANDS = {
    PASTE: "Paste",
    SYNTAX_CHECK: "Syntax Check",
    SAVE_PROJECT: "Save Project",
    SAVE_PROJECT_AS: "Save Project As",
    DISCONNECT: "Disconnect",
}

_NEVER = {
    READ_PROJECT_FROM_PLC: "Read Project from PLC",
    WRITE_PROJECT_INTO_PLC: "Write Project into PLC",
}


class ForbiddenCommandError(RuntimeError):
    """A WM_COMMAND outside ALLOWED_COMMANDS."""


def check_command(command_id: int) -> str:
    """The name of *command_id* if the runner may send it; raises ForbiddenCommandError if not."""
    name = ALLOWED_COMMANDS.get(command_id)
    if name is None:
        what = _NEVER.get(command_id, "not on the runner's allowlist")
        raise ForbiddenCommandError(f"refused WM_COMMAND {command_id} ({what})")
    return name


@dataclass(frozen=True)
class Window:
    """A visible top-level window."""

    hwnd: int
    cls: str
    title: str
    owner: int  # GW_OWNER, 0 for none
    enabled: bool
    rect: tuple[int, int, int, int]


@dataclass(frozen=True)
class Control:
    """A child window of a top-level window, at any depth.

    *text* is GetWindowText, which is empty for another process's edit controls: read
    those with ``Desktop.read_text``.
    """

    hwnd: int
    parent: int
    cls: str
    text: str
    id: int
    visible: bool
    enabled: bool
    rect: tuple[int, int, int, int]


class Desktop(ABC):
    """What the runner may do on the desktop."""

    def command(self, hwnd: int, command_id: int) -> str:
        """Post WM_COMMAND *command_id* to *hwnd*: the one way the runner sends a command.

        Raises ForbiddenCommandError, before anything is sent, for a command outside
        ALLOWED_COMMANDS. Returns the command's name.
        """
        name = check_command(command_id)
        self._post_command(hwnd, command_id)
        return name

    @abstractmethod
    def _post_command(self, hwnd: int, command_id: int) -> None: ...

    @abstractmethod
    def click_processes(self) -> list[int]:
        """Pids of every process whose image name is CLICK.exe, any version."""

    @abstractmethod
    def click_windows(self) -> list[int]:
        """Every window ClickNick takes for a CLICK main window (``find_click_hwnds``)."""

    @abstractmethod
    def input_desktop(self) -> str | None:
        """The input desktop's name (``Default`` when unlocked), or None if it cannot be opened."""

    @abstractmethod
    def launch(self, exe: Path) -> int:
        """Start *exe* in its own folder; its pid."""

    @abstractmethod
    def alive(self, pid: int) -> bool:
        """Whether the process the runner launched as *pid* is still running."""

    @abstractmethod
    def terminate(self, pid: int) -> None:
        """End the process the runner launched as *pid*, without asking it."""

    @abstractmethod
    def windows(self, pid: int) -> list[Window]:
        """The visible top-level windows of *pid*."""

    @abstractmethod
    def controls(self, hwnd: int) -> list[Control]:
        """Every child window of *hwnd*, at any depth."""

    @abstractmethod
    def read_text(self, hwnd: int) -> str | None:
        """*hwnd*'s text by WM_GETTEXT, or None if it does not answer."""

    @abstractmethod
    def set_text(self, hwnd: int, text: str) -> bool:
        """WM_SETTEXT; whether it was answered."""

    @abstractmethod
    def button_checked(self, hwnd: int) -> int | None:
        """BM_GETCHECK, or None if it does not answer."""

    @abstractmethod
    def list_view_counts(self, hwnd: int) -> tuple[int, int] | None:
        """A list view's (LVM_GETITEMCOUNT, LVM_GETSELECTEDCOUNT), or None if it does not answer."""

    @abstractmethod
    def press(self, hwnd: int) -> None:
        """Post BM_CLICK to the button *hwnd*."""

    @abstractmethod
    def close(self, hwnd: int) -> None:
        """Post WM_CLOSE to *hwnd*."""

    @abstractmethod
    def idle(self, hwnd: int, timeout: float) -> bool:
        """Whether *hwnd*'s thread answers WM_NULL within *timeout* seconds."""

    @abstractmethod
    def screenshot(self, hwnd: int, path: Path) -> bool:
        """Save *hwnd* as a PNG at *path*; whether it could."""

    @abstractmethod
    def set_clipboard(self, payload: bytes, owner: int) -> None:
        """Put *payload* on the clipboard in CLICK's format, owned by *owner*."""

    @abstractmethod
    def temp_dir(self, hwnd: int) -> Path:
        """The temp folder of the CLICK main window *hwnd* (``click_temp_dir``)."""


# ---------------------------------------------------------------------------
# Win32
# ---------------------------------------------------------------------------

WM_NULL = 0x0000
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
BM_GETCHECK = 0x00F0
BM_CLICK = 0x00F5
LVM_GETITEMCOUNT = 0x1004
LVM_GETSELECTEDCOUNT = 0x1032
SMTO_ABORTIFHUNG = 0x0002
GW_OWNER = 4
DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2
TH32CS_SNAPPROCESS = 0x00000002
_MESSAGE_TIMEOUT_MS = 5000
_ULONG_PTR = ctypes.c_size_t


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", _ULONG_PTR),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(_ULONG_PTR),
    ]
    user32.SendMessageTimeoutW.restype = _ULONG_PTR
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    return user32


def _png(width: int, height: int, bgra: bytes) -> bytes:
    """A PNG of top-down BGRA pixels."""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        row = bgra[y * stride : (y + 1) * stride]
        for x in range(0, len(row), 4):
            raw += bytes((row[x + 2], row[x + 1], row[x]))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


class Win32Desktop(Desktop):
    """The real desktop. Messages are posted or sent with a timeout, so a hung CLICK cannot hang it."""

    def __init__(self) -> None:
        self._user32 = _user32()
        self._processes: dict[int, subprocess.Popen[bytes]] = {}

    def _send(self, hwnd: int, msg: int, wparam: int = 0, lparam: object = 0) -> int | None:
        result = _ULONG_PTR()
        answered = self._user32.SendMessageTimeoutW(
            hwnd,
            msg,
            wparam,
            lparam,
            SMTO_ABORTIFHUNG,
            _MESSAGE_TIMEOUT_MS,
            ctypes.byref(result),
        )
        return result.value if answered else None

    def _post(self, hwnd: int, msg: int, wparam: int = 0) -> None:
        if not self._user32.PostMessageW(hwnd, msg, wparam, 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def _post_command(self, hwnd: int, command_id: int) -> None:
        self._post(hwnd, WM_COMMAND, command_id)

    def click_processes(self) -> list[int]:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot in (None, wintypes.HANDLE(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        found: list[int] = []
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(_ProcessEntry)
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.szExeFile.casefold() == "click.exe":
                    found.append(entry.th32ProcessID)
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return found

    def click_windows(self) -> list[int]:
        from clicknick.ladder.clipboard import find_click_hwnds

        return find_click_hwnds()

    def input_desktop(self) -> str | None:
        handle = self._user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            if not self._user32.GetUserObjectInformationW(
                handle, UOI_NAME, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)
            ):
                return None
            return buffer.value
        finally:
            self._user32.CloseDesktop(handle)

    def launch(self, exe: Path) -> int:
        process = subprocess.Popen([str(exe)], cwd=str(exe.parent))
        self._processes[process.pid] = process
        return process.pid

    def alive(self, pid: int) -> bool:
        return self._processes[pid].poll() is None

    def terminate(self, pid: int) -> None:
        self._processes[pid].kill()

    def windows(self, pid: int) -> list[Window]:
        import win32gui
        import win32process

        found: list[Window] = []

        def callback(hwnd: int, _: object) -> bool:
            if (
                win32gui.IsWindowVisible(hwnd)
                and win32process.GetWindowThreadProcessId(hwnd)[1] == pid
            ):
                found.append(
                    Window(
                        hwnd=hwnd,
                        cls=win32gui.GetClassName(hwnd),
                        title=win32gui.GetWindowText(hwnd),
                        owner=win32gui.GetWindow(hwnd, GW_OWNER),
                        enabled=bool(win32gui.IsWindowEnabled(hwnd)),
                        rect=tuple(win32gui.GetWindowRect(hwnd)),
                    )
                )
            return True

        win32gui.EnumWindows(callback, None)
        return found

    def controls(self, hwnd: int) -> list[Control]:
        import win32gui

        found: list[Control] = []

        def callback(child: int, _: object) -> bool:
            try:
                found.append(
                    Control(
                        hwnd=child,
                        parent=win32gui.GetParent(child),
                        cls=win32gui.GetClassName(child),
                        text=win32gui.GetWindowText(child),
                        id=win32gui.GetDlgCtrlID(child),
                        visible=bool(win32gui.IsWindowVisible(child)),
                        enabled=bool(win32gui.IsWindowEnabled(child)),
                        rect=tuple(win32gui.GetWindowRect(child)),
                    )
                )
            except win32gui.error:
                pass  # It closed while being listed
            return True

        try:
            win32gui.EnumChildWindows(hwnd, callback, None)
        except win32gui.error:
            pass  # No children, or the window closed
        return found

    def read_text(self, hwnd: int) -> str | None:
        length = self._send(hwnd, WM_GETTEXTLENGTH)
        if length is None:
            return None
        buffer = ctypes.create_unicode_buffer(length + 1)
        copied = self._send(hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buffer))
        if copied is None:
            return None
        return buffer.value

    def set_text(self, hwnd: int, text: str) -> bool:
        buffer = ctypes.create_unicode_buffer(text)
        return self._send(hwnd, WM_SETTEXT, 0, ctypes.addressof(buffer)) is not None

    def button_checked(self, hwnd: int) -> int | None:
        return self._send(hwnd, BM_GETCHECK)

    def list_view_counts(self, hwnd: int) -> tuple[int, int] | None:
        items = self._send(hwnd, LVM_GETITEMCOUNT)
        selected = self._send(hwnd, LVM_GETSELECTEDCOUNT)
        if items is None or selected is None:
            return None
        return items, selected

    def press(self, hwnd: int) -> None:
        self._post(hwnd, BM_CLICK)

    def close(self, hwnd: int) -> None:
        self._post(hwnd, WM_CLOSE)

    def idle(self, hwnd: int, timeout: float) -> bool:
        result = _ULONG_PTR()
        return bool(
            self._user32.SendMessageTimeoutW(
                hwnd,
                WM_NULL,
                0,
                0,
                SMTO_ABORTIFHUNG,
                max(1, int(timeout * 1000)),
                ctypes.byref(result),
            )
        )

    def screenshot(self, hwnd: int, path: Path) -> bool:
        import win32gui
        import win32ui

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return False
        window_dc = win32gui.GetWindowDC(hwnd)
        source = win32ui.CreateDCFromHandle(window_dc)
        memory = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(source, width, height)
            memory.SelectObject(bitmap)
            self._user32.PrintWindow(hwnd, memory.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT
            bits = bitmap.GetBitmapBits(True)
        finally:
            memory.DeleteDC()
            source.DeleteDC()
            win32gui.ReleaseDC(hwnd, window_dc)
            win32gui.DeleteObject(bitmap.GetHandle())
        path.write_bytes(_png(width, height, bits))
        return True

    def set_clipboard(self, payload: bytes, owner: int) -> None:
        from clicknick.ladder.clipboard import copy_to_clipboard

        copy_to_clipboard(payload, owner_hwnd=owner)

    def temp_dir(self, hwnd: int) -> Path:
        from clicknick.utils.click_temp import click_temp_dir

        return click_temp_dir(hwnd)
