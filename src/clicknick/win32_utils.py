"""
win32_utils.py - Windows API utilities using pywin32.

Provides window detection, control manipulation, and input simulation
for interacting with Click PLC software windows.
"""

import ctypes
import json
import re

import win32api
import win32clipboard
import win32con
import win32gui
import win32process

# Windows message constants
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_SETTEXT = 0x000C
EM_SETSEL = 0x00B1

# Virtual key codes
VK_RETURN = 0x0D
VK_CONTROL = 0x11
VK_END = 0x23

# Input event types for SendInput
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]


class Win32API:
    """Windows API wrapper for window and control operations."""

    # --- Private Helper Methods ---

    def _find_window_by_pid(self, pid: int) -> int | None:
        """Find a window handle by process ID."""
        result = [None]

        def enum_callback(hwnd, _):
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if window_pid == pid and win32gui.IsWindowVisible(hwnd):
                result[0] = hwnd
                return False  # Stop enumeration
            return True

        win32gui.EnumWindows(enum_callback, None)
        return result[0]

    # --- Window Operations ---

    def win_exist(self, *, pid: str | None = None, hwnd: int | None = None) -> bool:
        """Check if a window exists by PID or HWND."""
        if hwnd is not None:
            return win32gui.IsWindow(hwnd)
        if pid is not None:
            return self._find_window_by_pid(int(pid)) is not None
        return False

    def get_foreground_hwnd(self) -> int:
        """Get the foreground (active) window handle."""
        return win32gui.GetForegroundWindow()

    def get_foreground_pid(self) -> str:
        """Get the PID of the foreground window as string."""
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return str(pid)

    def get_pid(self, hwnd: int) -> str:
        """Get PID for a window handle as string."""
        if not hwnd or not win32gui.IsWindow(hwnd):
            return ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return str(pid)

    def get_hwnd_by_pid(self, pid: str | int) -> int | None:
        """Get window handle for a process ID."""
        return self._find_window_by_pid(int(pid))

    def get_class(self, hwnd: int) -> str:
        """Get window class name."""
        if not hwnd or not win32gui.IsWindow(hwnd):
            return ""
        try:
            return win32gui.GetClassName(hwnd)
        except Exception:
            return ""

    def get_title(self, hwnd: int) -> str:
        """Get window title."""
        if not hwnd or not win32gui.IsWindow(hwnd):
            return ""
        try:
            return win32gui.GetWindowText(hwnd)
        except Exception:
            return ""

    def get_title_by_class(self, class_name: str) -> str:
        """Get window title by class name."""
        hwnd = win32gui.FindWindow(class_name, None)
        if hwnd:
            return win32gui.GetWindowText(hwnd)
        return ""

    def get_pos(self, hwnd: int) -> str:
        """Get window position as 'x,y,width,height' string."""
        if not hwnd or not win32gui.IsWindow(hwnd):
            return ""
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            return f"{left},{top},{width},{height}"
        except Exception:
            return ""

    def _find_window_by_title(self, title: str) -> int | None:
        """Find a window by partial title match."""
        result = [None]

        def enum_callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                if title in window_title:
                    result[0] = hwnd
                    return False
            return True

        win32gui.EnumWindows(enum_callback, None)
        return result[0]

    def activate(
        self,
        hwnd: int | None = None,
        *,
        title: str | None = None,
        class_name: str | None = None,
    ) -> bool:
        """Activate (bring to foreground) a window by handle, title, or class."""
        if hwnd is None:
            if class_name is not None:
                hwnd = win32gui.FindWindow(class_name, None)
            elif title is not None:
                hwnd = self._find_window_by_title(title)
        if not hwnd:
            return False
        try:
            # Try standard approach
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            # Workaround: simulate Alt key to allow SetForegroundWindow
            try:
                ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)  # Alt down
                ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)  # Alt up
                win32gui.SetForegroundWindow(hwnd)
                return True
            except Exception:
                return False

    def get_click_windows(self) -> str:
        """Get all Click.exe windows as JSON array."""
        results = []

        def enum_callback(hwnd, _):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                # Check if this is a Click.exe process
                try:
                    h_process = win32api.OpenProcess(
                        win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                        False,
                        pid,
                    )
                    try:
                        exe_path = win32process.GetModuleFileNameEx(h_process, 0)
                        exe_name = exe_path.split("\\")[-1].lower()
                        if exe_name != "click.exe":
                            return True
                    finally:
                        win32api.CloseHandle(h_process)
                except Exception:
                    return True

                title = win32gui.GetWindowText(hwnd)
                if title:  # Only include windows with titles
                    results.append({"index": len(results) + 1, "id": hex(hwnd), "title": title})
            except Exception:
                pass
            return True

        win32gui.EnumWindows(enum_callback, None)
        return json.dumps(results)

    # --- Control Operations ---

    def find_control(self, parent_hwnd: int, control_name: str) -> int | None:
        """
        Find a control by AHK-style name (e.g., 'Edit1', 'ComboBox2').

        Args:
            parent_hwnd: Handle to parent window
            control_name: AHK-style name like 'Edit1' (1-based index)

        Returns:
            Control HWND or None if not found
        """
        match = re.match(r"^(\D+)(\d+)$", control_name)
        if not match:
            return None

        class_name = match.group(1)
        index = int(match.group(2))  # 1-based in AHK

        controls: list[int] = []

        def enum_callback(hwnd, _):
            try:
                if win32gui.GetClassName(hwnd) == class_name:
                    controls.append(hwnd)
            except Exception:
                pass
            return True

        win32gui.EnumChildWindows(parent_hwnd, enum_callback, None)

        if 0 < index <= len(controls):
            return controls[index - 1]
        return None

    def _hwnd_to_control_name(self, parent_hwnd: int, control_hwnd: int) -> str:
        """Convert a control HWND to AHK-style name like 'Edit1'."""
        try:
            class_name = win32gui.GetClassName(control_hwnd)
        except Exception:
            return ""

        count = [0]
        found = [False]

        def enum_callback(hwnd, _):
            try:
                if win32gui.GetClassName(hwnd) == class_name:
                    count[0] += 1
                    if hwnd == control_hwnd:
                        found[0] = True
                        return False  # Stop enumeration
            except Exception:
                pass
            return True

        win32gui.EnumChildWindows(parent_hwnd, enum_callback, None)

        if found[0]:
            return f"{class_name}{count[0]}"
        return ""

    def get_focused_control(self, hwnd: int) -> str:
        """
        Get the AHK-style name of the focused control (e.g., 'Edit1').

        Requires thread attachment to get focus from another process.
        """
        if not hwnd or not win32gui.IsWindow(hwnd):
            return ""

        target_thread_id, _ = win32process.GetWindowThreadProcessId(hwnd)
        current_thread_id = win32api.GetCurrentThreadId()

        attached = False
        if target_thread_id != current_thread_id:
            attached = ctypes.windll.user32.AttachThreadInput(
                current_thread_id, target_thread_id, True
            )

        try:
            focus_hwnd = win32gui.GetFocus()
            if not focus_hwnd:
                return ""
            return self._hwnd_to_control_name(hwnd, focus_hwnd)
        except Exception:
            return ""
        finally:
            if attached:
                ctypes.windll.user32.AttachThreadInput(current_thread_id, target_thread_id, False)

    def get_control_pos(self, parent_hwnd: int, control_name: str) -> str:
        """Get control position relative to parent as 'x,y,width,height'."""
        ctrl_hwnd = self.find_control(parent_hwnd, control_name)
        if not ctrl_hwnd:
            return ""

        try:
            # Get control rect in screen coordinates
            ctrl_left, ctrl_top, ctrl_right, ctrl_bottom = win32gui.GetWindowRect(ctrl_hwnd)
            # Get parent rect
            parent_left, parent_top, _, _ = win32gui.GetWindowRect(parent_hwnd)
            # Calculate relative position
            x = ctrl_left - parent_left
            y = ctrl_top - parent_top
            width = ctrl_right - ctrl_left
            height = ctrl_bottom - ctrl_top
            return f"{x},{y},{width},{height}"
        except Exception:
            return ""

    def get_control_text(self, parent_hwnd: int, control_name: str) -> str:
        """Get text from a control."""
        ctrl_hwnd = self.find_control(parent_hwnd, control_name)
        if not ctrl_hwnd:
            return ""

        try:
            length = win32gui.SendMessage(ctrl_hwnd, WM_GETTEXTLENGTH, 0, 0)
            if length == 0:
                return ""
            buffer = ctypes.create_unicode_buffer(length + 1)
            win32gui.SendMessage(ctrl_hwnd, WM_GETTEXT, length + 1, buffer)
            return buffer.value
        except Exception:
            return ""

    def set_control_text(self, parent_hwnd: int, control_name: str, text: str) -> bool:
        """Set text in a control."""
        ctrl_hwnd = self.find_control(parent_hwnd, control_name)
        if not ctrl_hwnd:
            return False

        try:
            win32gui.SendMessage(ctrl_hwnd, WM_SETTEXT, 0, text)
            return True
        except Exception:
            return False

    def control_send_end(self, parent_hwnd: int, control_name: str) -> bool:
        """Send Ctrl+End to a control (like AHK's ControlSend ^{End})."""
        ctrl_hwnd = self.find_control(parent_hwnd, control_name)
        if not ctrl_hwnd:
            return False

        try:
            # Move selection to end of text (like Ctrl+End in edit controls)
            win32gui.SendMessage(ctrl_hwnd, EM_SETSEL, -1, -1)
            return True
        except Exception:
            return False

    # --- Input Operations ---

    def send_key(self, key: str) -> bool:
        """
        Send a keyboard key. Limited support for special keys.

        Supported: {Enter}, {Tab}, {Escape}, {Esc}
        """
        key_map = {
            "{Enter}": VK_RETURN,
            "{Tab}": win32con.VK_TAB,
            "{Escape}": win32con.VK_ESCAPE,
            "{Esc}": win32con.VK_ESCAPE,
        }

        vk = key_map.get(key)
        if vk is None:
            return False

        try:
            # Key down
            inputs = (INPUT * 2)()
            inputs[0].type = INPUT_KEYBOARD
            inputs[0].ki.wVk = vk
            inputs[0].ki.dwFlags = 0

            # Key up
            inputs[1].type = INPUT_KEYBOARD
            inputs[1].ki.wVk = vk
            inputs[1].ki.dwFlags = KEYEVENTF_KEYUP

            ctypes.windll.user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
            return True
        except Exception:
            return False

    # --- Clipboard Operations ---

    def set_clipboard(self, text: str) -> bool:
        """Set clipboard text content."""
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            return False


# Singleton instance
WIN32 = Win32API()
