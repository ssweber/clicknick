"""The desktop calls the CLICK runner makes (devtools/click_runner.py), and their Win32 version.

The runner drives CLICK only through ``Desktop``, so its logic is tested against a fake
(tests/test_click_runner.py) and this Win32 version stays thin: each method is one or two
Win32 calls with no decisions of its own.

Every ``WM_COMMAND`` goes through ``Desktop.command``, which refuses any command outside
``ALLOWED_COMMANDS``. Read Project, Write Project and Write Data are not in it, so the
runner cannot read a project from the PLC or write anything into it; Read Data from PLC,
which only reads the PLC's data values, is. The one mouse click the runner makes is posted to
CLICK's ladder view, through ``Desktop.click_ladder``, which finds the view itself.
"""

from __future__ import annotations

import ctypes
import struct
import subprocess
import time
import zlib
from abc import ABC, abstractmethod
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

# CLICK v4's command ids, from CLICK.exe's string table (probe of 2026-11-15)
PASTE = 0xE125  # MFC's ID_EDIT_PASTE
DELETE = 32777  # Edit > Delete: the instruction under the ladder's cursor
SYNTAX_CHECK = 32846
OPEN_PROJECT = 32772  # File > Open Project ("Open Project" in the string table, 2026-11-16)
SAVE_PROJECT = 32898
SAVE_PROJECT_AS = 32899
DISCONNECT = 32850
# File > Import > Nickname ("Import to Address Picker" in the string table). It opens an Open
# dialog with three import modes and writes the rows into SC_.mdb (live probe of 2026-11-15)
IMPORT_NICKNAME = 32900
# Program > Address Picker (Ctrl+T; "Address Picker" in the string table): CLICK's editor of
# nicknames and address comments (probe of 2026-11-16)
ADDRESS_PICKER = 32834
# System Configuration ("System Configuration" in the string table): the PLC's modules and the
# project's PLC Name, which it shows from Project.ini's [Sec20] Key1. Its OK saves setup into
# the project and is never pressed; Cancel closes it (live probe C2, 2026-11-16)
SYSTEM_CONFIGURATION = 32827
# PLC > Read Data from PLC: it reads the PLC's data values and saves them to a file. Write
# Data into PLC, beside it, writes a file's values into the PLC and is never sent (string
# table, probe of 2026-11-16)
READ_DATA_FROM_PLC = 32851
WRITE_DATA_INTO_PLC = 32852
READ_PROJECT_FROM_PLC = 32853
WRITE_PROJECT_INTO_PLC = 32854
# The ribbon's Instruction tab, which opens an instruction's dialog at the ladder's cursor.
# These ids are in no string table: CLICK.exe builds the ribbon in code, pushing each
# button's id beside its label ("Math..."). The same reading gives 32850 for "Disconnect..."
# and 32853 for "Read Project from PLC...", as the string table does (probe of 2026-11-15).
OUT_DIALOG = 50010
MATH_DIALOG = 50030
COPY_DIALOG = 50040
# "Receive..." pushes 50060 (and "Send..." 50061) the same way; live probes r1 and r2
# (2026-11-16) opened the Receive dialog by it (Inst_RD.dll's template, titled "Receive")
RECEIVE_DIALOG = 50060
# The ribbon's Contact(NO), Compare and Search push 50001, 50004 and 50041 the same way. Live
# probes d1 to d3 (2026-11-17, job copy-encodings) opened "Contact Normally Open"
# (Inst_ContactNO.dll), "Compare (A with B)" (Inst_Compare.dll) and "Search" (Inst_Search.dll)
# by them
CONTACT_NO_DIALOG = 50001
COMPARE_DIALOG = 50004
SEARCH_DIALOG = 50041
# MFC's ID_EDIT_COPY: Edit > Copy puts what the ladder has selected on the clipboard, and
# nothing else (live probe d2, 2026-11-17, job copy-encodings)
EDIT_COPY = 0xE122

ALLOWED_COMMANDS = {
    PASTE: "Paste",
    DELETE: "Delete",
    SYNTAX_CHECK: "Syntax Check",
    OPEN_PROJECT: "Open Project",
    SAVE_PROJECT: "Save Project",
    SAVE_PROJECT_AS: "Save Project As",
    DISCONNECT: "Disconnect",
    IMPORT_NICKNAME: "Import Nickname",
    READ_DATA_FROM_PLC: "Read Data from PLC",
    ADDRESS_PICKER: "Address Picker",
    SYSTEM_CONFIGURATION: "System Configuration",
    OUT_DIALOG: "Out...",
    MATH_DIALOG: "Math...",
    COPY_DIALOG: "Copy...",
    RECEIVE_DIALOG: "Receive...",
    CONTACT_NO_DIALOG: "Contact(NO)...",
    COMPARE_DIALOG: "Compare...",
    SEARCH_DIALOG: "Search...",
    EDIT_COPY: "Copy",
}

# The ladder view: the one visible child of CLICK's main window of this class (live probe d2,
# 2026-11-17). The only window a mouse click is posted to (``Desktop.click_ladder``)
LADDER_VIEW_CLASS = "AfxFrameOrView100u"

_NEVER = {
    WRITE_DATA_INTO_PLC: "Write Data into PLC",
    READ_PROJECT_FROM_PLC: "Read Project from PLC",
    WRITE_PROJECT_INTO_PLC: "Write Project into PLC",
}


class ForbiddenCommandError(RuntimeError):
    """A WM_COMMAND outside ALLOWED_COMMANDS."""


class LadderViewError(RuntimeError):
    """The main window has no one visible ladder view to click in."""


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

    def click_ladder(self, main: int, x: int, y: int) -> int:
        """Post a left click (button down, then up) at the client point (*x*, *y*) of the
        ladder view of the main window *main*: the one way the runner clicks.

        The view is the one visible child of *main* of class ``LADDER_VIEW_CLASS``; raises
        LadderViewError, before anything is posted, when there is none or more than one.
        Returns the view's hwnd.
        """
        views = [c for c in self.controls(main) if c.cls == LADDER_VIEW_CLASS and c.visible]
        if len(views) != 1:
            raise LadderViewError(
                f"{len(views)} visible ladder views ({LADDER_VIEW_CLASS}) in window {main}"
            )
        self._post_click(views[0].hwnd, x, y)
        return views[0].hwnd

    @abstractmethod
    def _post_click(self, hwnd: int, x: int, y: int) -> None: ...

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
        """Start *exe* in its own folder; its pid. It ends when the runner's process does."""

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
    def exists(self, hwnd: int) -> bool:
        """Whether *hwnd* is still a window (IsWindow); it sends no message."""

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
    def list_view_items(self, hwnd: int) -> int | None:
        """A list view's LVM_GETITEMCOUNT, or None if it does not answer."""

    @abstractmethod
    def combo_box(self, hwnd: int) -> tuple[list[str], int] | None:
        """A ComboBox's items (CB_GETLBTEXT) and the index selected (CB_GETCURSEL, -1 for
        none), or None if it does not answer. It only reads."""

    @abstractmethod
    def edit_limit(self, hwnd: int) -> int | None:
        """An edit's EM_GETLIMITTEXT, the most characters typing can put in it, or None if
        it does not answer. WM_SETTEXT is not held to it."""

    @abstractmethod
    def status_bar(self, hwnd: int) -> list[str] | None:
        """The pane texts of the common-control status bar *hwnd* (SB_GETTEXT), or None.

        None when the bar does not answer. Raises OSError when the buffer SB_GETTEXT needs
        in the bar's process cannot be used. It only reads; the buffer is freed again.
        """

    @abstractmethod
    def press(self, hwnd: int) -> None:
        """Post BM_CLICK to the button *hwnd*."""

    @abstractmethod
    def send_press(self, hwnd: int) -> bool:
        """Send BM_CLICK to the button *hwnd*; whether it was answered within 5 s.

        Sent, not posted, so the click has been handled when this returns True. False when
        it was not answered in time, as when the click opens a modal box: the box is then
        still open.
        """

    @abstractmethod
    def close(self, hwnd: int) -> None:
        """Post WM_CLOSE to *hwnd*."""

    @abstractmethod
    def send_key(self, hwnd: int, vk: int) -> bool:
        """Send WM_KEYDOWN then WM_KEYUP for the virtual key *vk* to *hwnd*; whether both
        were answered, each within 5 s.

        A message to that one window, as WM_SETTEXT is: no global input, so nothing reaches
        another window, whatever has the focus. Sent, not posted, so the key has been handled
        when this returns True. False when a message was not answered in time, as when the
        key opens a modal box (the box is then still open); no WM_KEYUP follows a WM_KEYDOWN
        that was not answered.
        """

    @abstractmethod
    def send_chars(self, hwnd: int, text: str) -> bool:
        """Send a WM_CHAR to *hwnd* for each character of *text*; whether all were answered."""

    @abstractmethod
    def idle(self, hwnd: int, timeout: float) -> bool:
        """Whether *hwnd*'s thread answers WM_NULL within *timeout* seconds."""

    @abstractmethod
    def screenshot(self, hwnd: int, path: Path) -> bool:
        """Save the screen where *hwnd* is as a PNG at *path*; whether it could.

        It is the screen, not the window: whatever lies over CLICK there is in the PNG.
        """

    @abstractmethod
    def set_clipboard(self, payload: bytes, owner: int) -> None:
        """Put *payload* on the clipboard in CLICK's format, owned by *owner*."""

    @abstractmethod
    def empty_clipboard(self) -> None:
        """Empty the clipboard, every format."""

    @abstractmethod
    def read_clipboard(self) -> bytes | None:
        """The clipboard's data in CLICK's format, or None if it holds none. It only reads."""

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
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_COMMAND = 0x0111
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
BM_GETCHECK = 0x00F0
EM_GETLIMITTEXT = 0x00D5
CB_GETCOUNT = 0x0146
CB_GETCURSEL = 0x0147
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149
CB_ERR = 0xFFFFFFFF
BM_CLICK = 0x00F5
LVM_GETITEMCOUNT = 0x1004
SB_GETPARTS = 0x0406
SB_GETTEXTLENGTHW = 0x040C
SB_GETTEXTW = 0x040D
SMTO_ABORTIFHUNG = 0x0002
GW_OWNER = 4
DESKTOP_READOBJECTS = 0x0001
UOI_NAME = 2
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # For IsWow64Process
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_MAX_PANES = 32
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
_MESSAGE_TIMEOUT_MS = 5000
# How often, and how far apart, opening the clipboard is tried: another program may hold it
_CLIPBOARD_TRIES = 20
_CLIPBOARD_DELAY = 0.05
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
    return user32


def _png(width: int, height: int, bgra: bytes) -> bytes:
    """A PNG of top-down 32-bit BGRA pixels."""
    rgb = bytearray(width * height * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride : (y + 1) * stride] for y in range(height))

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


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.VirtualAllocEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_size_t,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.VirtualAllocEx.restype = ctypes.c_void_p
    kernel32.VirtualFreeEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_size_t,
        wintypes.DWORD,
    ]
    kernel32.VirtualFreeEx.restype = wintypes.BOOL
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsWow64Process.restype = wintypes.BOOL
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    return kernel32


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def kill_on_close(process: int) -> int:
    """Put the process handle *process* in a new job that kills it when the job closes.

    Returns the job's handle. Windows closes it when this process ends, however it ends
    (killed, Ctrl+Break, its console closed), and the process in the job dies with it.
    """
    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
    ) or not kernel32.AssignProcessToJobObject(job, process):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(job)
        raise error
    return job


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def capture_screen(left: int, top: int, width: int, height: int) -> bytes:
    """The screen's pixels in a rectangle, as top-down 32-bit BGRA whatever the display's depth."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]

    header = _BitmapInfoHeader()
    header.biSize = ctypes.sizeof(_BitmapInfoHeader)
    header.biWidth = width
    header.biHeight = -height  # Top-down
    header.biPlanes = 1
    header.biBitCount = 32  # A 32-bit DIB section, so a 16-bit display (RDP) reads the same
    bits = ctypes.c_void_p()
    screen = user32.GetDC(None)
    if not screen:
        raise ctypes.WinError(ctypes.get_last_error())
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateDIBSection(screen, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    try:
        if not memory or not bitmap or not bits.value:
            raise ctypes.WinError(ctypes.get_last_error())
        previous = gdi32.SelectObject(memory, bitmap)
        copied = gdi32.BitBlt(memory, 0, 0, width, height, screen, left, top, SRCCOPY | CAPTUREBLT)
        gdi32.SelectObject(memory, previous)
        if not copied:
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.string_at(bits.value, width * height * 4)
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory:
            gdi32.DeleteDC(memory)
        user32.ReleaseDC(None, screen)


class Win32Desktop(Desktop):
    """The real desktop. Messages are posted or sent with a timeout, so a hung CLICK cannot hang it."""

    def __init__(self) -> None:
        self._user32 = _user32()
        self._processes: dict[int, subprocess.Popen[bytes]] = {}
        self._jobs: dict[int, int] = {}  # Kept open for as long as the runner runs

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

    def _post(self, hwnd: int, msg: int, wparam: int = 0, lparam: int = 0) -> None:
        if not self._user32.PostMessageW(hwnd, msg, wparam, lparam):
            raise ctypes.WinError(ctypes.get_last_error())

    def _post_command(self, hwnd: int, command_id: int) -> None:
        self._post(hwnd, WM_COMMAND, command_id)

    def _post_click(self, hwnd: int, x: int, y: int) -> None:
        point = (y & 0xFFFF) << 16 | x & 0xFFFF
        self._post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, point)
        self._post(hwnd, WM_LBUTTONUP, 0, point)

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
        try:
            handle = int(process._handle)  # pyright: ignore[reportAttributeAccessIssue]
            self._jobs[process.pid] = kill_on_close(handle)
        except BaseException:
            process.kill()  # A CLICK that could outlive the runner does not run at all
            process.wait()
            raise
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

    def exists(self, hwnd: int) -> bool:
        import win32gui

        return bool(win32gui.IsWindow(hwnd))

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

    def list_view_items(self, hwnd: int) -> int | None:
        return self._send(hwnd, LVM_GETITEMCOUNT)

    def combo_box(self, hwnd: int) -> tuple[list[str], int] | None:
        count = self._send(hwnd, CB_GETCOUNT)
        if count is None or count & CB_ERR == CB_ERR:
            return None
        items: list[str] = []
        for index in range(count):
            length = self._send(hwnd, CB_GETLBTEXTLEN, index)
            if length is None or length & CB_ERR == CB_ERR:
                return None
            buffer = ctypes.create_unicode_buffer(length + 1)
            if self._send(hwnd, CB_GETLBTEXT, index, ctypes.addressof(buffer)) is None:
                return None
            items.append(buffer.value)
        selected = self._send(hwnd, CB_GETCURSEL)
        if selected is None:
            return None
        return items, -1 if selected & CB_ERR == CB_ERR else selected

    def edit_limit(self, hwnd: int) -> int | None:
        return self._send(hwnd, EM_GETLIMITTEXT)

    def status_bar(self, hwnd: int) -> list[str] | None:
        """SB_GETTEXT for each pane, through a buffer in the bar's process."""
        import win32gui
        import win32process

        if win32gui.GetClassName(hwnd) != "msctls_statusbar32":
            return None  # SB_* means nothing known to any other class
        parts = self._send(hwnd, SB_GETPARTS)
        if not parts:
            return None

        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        kernel32 = _kernel32()
        access = PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE
        process = kernel32.OpenProcess(access | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        size = 1024 * 2
        remote = kernel32.VirtualAllocEx(
            process, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        try:
            if not remote:
                raise ctypes.WinError(ctypes.get_last_error())
            wow64 = wintypes.BOOL()
            if not kernel32.IsWow64Process(process, ctypes.byref(wow64)):
                raise ctypes.WinError(ctypes.get_last_error())
            if wow64.value and remote > 0xFFFFFFFF:
                # A 32-bit CLICK would get the address cut to 32 bits and write elsewhere
                raise OSError(
                    f"the buffer for SB_GETTEXT lies at {remote:#x}, out of reach of a 32-bit CLICK"
                )
            panes: list[str] = []
            for index in range(min(parts, _MAX_PANES)):
                length = self._send(hwnd, SB_GETTEXTLENGTHW, index)
                if length is None:
                    return None
                if length & 0xFFFF >= size // 2:
                    panes.append("")
                    continue
                if self._send(hwnd, SB_GETTEXTW, index, remote) is None:
                    return None
                buffer = ctypes.create_unicode_buffer(size // 2)
                read = ctypes.c_size_t()
                if not kernel32.ReadProcessMemory(
                    process, remote, buffer, size, ctypes.byref(read)
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                panes.append(buffer.value)
            return panes
        finally:
            if remote:
                kernel32.VirtualFreeEx(process, remote, 0, MEM_RELEASE)
            kernel32.CloseHandle(process)

    def press(self, hwnd: int) -> None:
        self._post(hwnd, BM_CLICK)

    def send_press(self, hwnd: int) -> bool:
        return self._send(hwnd, BM_CLICK) is not None

    def close(self, hwnd: int) -> None:
        self._post(hwnd, WM_CLOSE)

    def send_key(self, hwnd: int, vk: int) -> bool:
        scan = self._user32.MapVirtualKeyW(vk, 0) & 0xFF  # MAPVK_VK_TO_VSC
        if self._send(hwnd, WM_KEYDOWN, vk, 1 | scan << 16) is None:
            return False
        return self._send(hwnd, WM_KEYUP, vk, 1 | scan << 16 | 1 << 30 | 1 << 31) is not None

    def send_chars(self, hwnd: int, text: str) -> bool:
        return all(self._send(hwnd, WM_CHAR, ord(char), 1) is not None for char in text)

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
        """Copy *hwnd*'s rectangle from the screen, as it shows (windows on top included).

        It sends CLICK no message (PrintWindow would, and waits on a hung CLICK forever).
        """
        import win32gui

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return False
        path.write_bytes(_png(width, height, capture_screen(left, top, width, height)))
        return True

    def set_clipboard(self, payload: bytes, owner: int) -> None:
        from clicknick.ladder.clipboard import copy_to_clipboard

        copy_to_clipboard(payload, owner_hwnd=owner)

    def empty_clipboard(self) -> None:
        from clicknick.ladder.clipboard import clear_clipboard

        clear_clipboard(0)

    def read_clipboard(self) -> bytes | None:
        """CLICK's format is the one ``clicknick.ladder.clipboard`` pastes in (522, in the
        private range CF_PRIVATEFIRST to CF_PRIVATELAST: it has no registered name)."""
        import win32clipboard

        from clicknick.ladder.clipboard import CLICK_CLIPBOARD_FORMAT

        for _ in range(_CLIPBOARD_TRIES):
            try:
                win32clipboard.OpenClipboard(0)
                break
            except win32clipboard.error:
                time.sleep(_CLIPBOARD_DELAY)
        else:
            raise OSError(f"the clipboard could not be opened in {_CLIPBOARD_TRIES} tries")
        try:
            if not win32clipboard.IsClipboardFormatAvailable(CLICK_CLIPBOARD_FORMAT):
                return None
            return bytes(win32clipboard.GetClipboardData(CLICK_CLIPBOARD_FORMAT))
        finally:
            win32clipboard.CloseClipboard()

    def temp_dir(self, hwnd: int) -> Path:
        from clicknick.utils.click_temp import click_temp_dir

        return click_temp_dir(hwnd)
