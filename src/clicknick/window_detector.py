import json
import re

from .shared_ahk import AHK


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

            # Check if window still exists
            result = AHK.f("WinExist", f"ahk_pid {window_pid}")
            return bool(result)
        except Exception as e:
            print(f"Error checking window existence: {e}")
            return False

    def detect_child_window(self, click_pid: str) -> tuple[str, str, str] | None:
        """
        Detect if the active window is our connected Click.exe instance.

        Returns:
            tuple: (window_id, window_class, edit_control) or None if not valid
        """
        try:
            # Get the active window PID
            active_window_pid = AHK.f("WinGet", "PID", "A")  # "A" means active window

            # Check if active window is our Click.exe instance
            if active_window_pid != click_pid:
                return None

            # Get window class
            active_window_id = AHK.f("WinGet", "ID", "A")
            window_class = AHK.f("WinGetClass", f"ahk_id {active_window_id}")

            # Check if it's a recognized window class
            if window_class not in self.window_mapping:
                return None

            if window_class == "#32770":
                window_name = AHK.f("WinGetTitle", "ahk_class #32770")
                if "Replace" not in window_name and "Find" not in window_name:
                    return None

            # Get focused control
            focused_control = AHK.f("ControlGetFocus", f"ahk_id {active_window_id}")
            if not focused_control:
                return None

            # Check if focused control is in our list of edit controls
            allowed_fields = self.window_mapping[window_class]
            if focused_control not in allowed_fields:
                return None

            # We found a valid popup with a focused edit control
            return (active_window_id, window_class, focused_control)

        except Exception as e:
            print(f"Error detecting popup window: {e}")
            return None

    def field_has_text(self, field, window_id) -> bool:
        """Check if the current field already has text in it."""
        try:
            field_text = AHK.f_raw("ControlGetText", field, f"ahk_id {window_id}")
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

    def get_click_instances(self) -> list[tuple[str, str, str]]:
        """
        Get all running Click.exe instances.

        Returns:
            List of tuples (pid, title, filename)
        """
        click_instances = []

        try:
            # Get all Click.exe windows
            click_windows_json = AHK.f("WinGetClick")

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

                window_pid = AHK.f("WinGet", "PID", f"ahk_id {window_id}")

                # Extract .ckp filename using centralized parser
                filename = ClickWindowDetector.parse_click_filename(window_title)
                if filename:
                    click_instances.append((window_pid, window_title, filename))

            return click_instances

        except Exception as e:
            print(f"Error getting Click instances: {e}")
            return click_instances

    def get_window_handle(self, pid):
        """
        Get the window handle for a process ID using AHK.

        Args:
            pid: Process ID (string or int)

        Returns:
            Window handle (hwnd) or None if not found
        """
        try:
            # Get window ID using AHK
            window_id = AHK.f("WinGet", "ID", f"ahk_pid {pid}")
            if window_id:
                return int(window_id)
            return None
        except Exception as e:
            print(f"Error getting window handle: {e}")
            return None

    def update(self) -> tuple[bool, list[str]]:
        """
        Update window and field detection.
        Returns: Tuple of (is_valid_field, allowed_address_types)
        """
        # Get the current window and field info
        return self.update_window_info(self.current_window, self.current_field)

    def get_window_title(self, window_id: str) -> str | None:
        """Get current title of a specific window using AHK."""
        try:
            return AHK.f("WinGetTitle", f"ahk_id {window_id}")
        except Exception:
            return None

    def update_window_info(self, window_class: str, field: str) -> tuple[bool, list[str]]:
        """
        Update window and field detection with provided window and field.
        Returns: Tuple of (is_valid_field, allowed_address_types)
        """
        self.current_window = window_class
        self.current_field = field

        # Early return if no valid window
        if not self.current_window or self.current_window not in self.window_mapping:
            return False, []

        # Return result
        if not self.current_field or self.current_field not in self.window_mapping.get(
            self.current_window, {}
        ):
            return False, []

        # Get allowed address types
        allowed_addresses = self.window_mapping.get(self.current_window, {}).get(
            self.current_field, []
        )
        return True, allowed_addresses
