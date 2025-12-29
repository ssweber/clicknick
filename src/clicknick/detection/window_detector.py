import json
import re
from dataclasses import dataclass

from ..utils.win32_utils import WIN32


@dataclass
class ChildWindowInfo:
    """Information about a detected Click.exe child window."""

    window_id: int  # HWND as integer
    window_class: str
    edit_control: str


@dataclass
class ClickInstance:
    """Information about a running Click.exe instance."""

    pid: str
    title: str
    filename: str
    hwnd: int


@dataclass
class WindowFieldInfo:
    """Result of window/field detection."""

    is_valid: bool
    allowed_address_types: list[str]


class ClickWindowDetector:
    """Detects Click PLC windows and their focused fields."""

    def __init__(self, window_mapping: dict, clicknick):
        self.window_mapping = window_mapping
        self.current_window: str | None = None
        self.current_field: str | None = None

    def check_window_exists(self, window_pid: str) -> bool:
        """
        Check if a window with the given PID still exists.

        Args:
            window_pid: The PID of the window to check

        Returns:
            bool: True if the window exists, False otherwise
        """
        try:
            if not window_pid:
                return False
            return WIN32.win_exist(pid=window_pid)
        except Exception as e:
            print(f"Error checking window existence: {e}")
            return False

    def detect_child_window(self, click_pid: str) -> ChildWindowInfo | None:
        """
        Detect if the active window is our connected Click.exe instance.

        Returns:
            ChildWindowInfo or None if not valid
        """
        try:
            # Get the active window PID
            active_window_pid = WIN32.get_foreground_pid()

            # Check if active window is our Click.exe instance
            if active_window_pid != click_pid:
                return None

            # Get window handle and class
            active_window_hwnd = WIN32.get_foreground_hwnd()
            window_class = WIN32.get_class(active_window_hwnd)

            # Check if it's a recognized window class
            if window_class not in self.window_mapping:
                return None

            if window_class == "#32770":
                window_name = WIN32.get_title_by_class("#32770")
                if "Replace" not in window_name and "Find" not in window_name:
                    return None

            # Get focused control
            # TfrmDataView creates inline edit controls dynamically, requiring GetGUIThreadInfo
            use_gui_thread_info = window_class == "TfrmDataView"
            focused_control = WIN32.get_focused_control(active_window_hwnd, use_gui_thread_info)
            if not focused_control:
                return None

            # Check if focused control is in our list of edit controls
            allowed_fields = self.window_mapping[window_class]
            if focused_control not in allowed_fields:
                return None

            # We found a valid popup with a focused edit control
            return ChildWindowInfo(active_window_hwnd, window_class, focused_control)

        except Exception as e:
            print(f"Error detecting popup window: {e}")
            return None

    def field_has_text(self, field: str, window_id: int) -> bool:
        """Check if the current field already has text in it."""
        try:
            field_text = WIN32.get_control_text(window_id, field)
            return field_text.strip() != ""
        except Exception as e:
            print(f"Error checking field text: {e}")
            return False

    @staticmethod
    def parse_click_filename(title: str) -> str | None:
        """Extract Click filename from window title."""
        if not title:
            return None
        match = re.search(r"- ([^\\]+\.ckp)", title)
        return match.group(1) if match else None

    def get_click_instances(self) -> list[ClickInstance]:
        """
        Get all running Click.exe instances.

        Returns:
            List of ClickInstance objects
        """
        click_instances: list[ClickInstance] = []

        try:
            # Get all Click.exe windows
            click_windows_json = WIN32.get_click_windows()

            if not click_windows_json:
                return click_instances

            # Parse the JSON response
            try:
                click_windows = json.loads(click_windows_json)
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON: {e}")
                return click_instances

            # Process each window
            for window in click_windows:
                window_id = window.get("id")
                window_title = window.get("title")

                if not window_id or not window_title:
                    continue

                # Convert hex string to int
                hwnd = int(window_id, 16) if isinstance(window_id, str) else int(window_id)
                window_pid = WIN32.get_pid(hwnd)

                # Extract .ckp filename using centralized parser
                filename = ClickWindowDetector.parse_click_filename(window_title)
                if filename:
                    click_instances.append(ClickInstance(window_pid, window_title, filename, hwnd))

            return click_instances

        except Exception as e:
            print(f"Error getting Click instances: {e}")
            return click_instances

    def get_window_handle(self, pid) -> int | None:
        """
        Get the window handle for a process ID.

        Args:
            pid: Process ID (string or int)

        Returns:
            Window handle (hwnd) or None if not found
        """
        try:
            return WIN32.get_hwnd_by_pid(pid)
        except Exception as e:
            print(f"Error getting window handle: {e}")
            return None

    def update(self) -> WindowFieldInfo:
        """
        Update window and field detection.
        Returns: WindowFieldInfo with validity and allowed address types
        """
        # Get the current window and field info
        return self.update_window_info(self.current_window, self.current_field)

    def get_window_title(self, window_id: int) -> str | None:
        """Get current title of a specific window."""
        try:
            return WIN32.get_title(window_id)
        except Exception:
            return None

    def update_window_info(self, window_class: str, field: str) -> WindowFieldInfo:
        """
        Update window and field detection with provided window and field.
        Returns: WindowFieldInfo with validity and allowed address types
        """
        self.current_window = window_class
        self.current_field = field

        # Early return if no valid window
        if not self.current_window or self.current_window not in self.window_mapping:
            return WindowFieldInfo(False, [])

        # Return result
        if not self.current_field or self.current_field not in self.window_mapping.get(
            self.current_window, {}
        ):
            return WindowFieldInfo(False, [])

        # Get allowed address types
        allowed_addresses = self.window_mapping.get(self.current_window, {}).get(
            self.current_field, []
        )
        return WindowFieldInfo(True, allowed_addresses)
