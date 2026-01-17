# Detection Module

This module handles detection of CLICK PLC Programming Software windows and edit controls for overlay positioning.

## Overview

The detection system monitors Windows for CLICK instruction dialogs and identifies the appropriate edit controls for nickname autocomplete:
- Polls for Click.exe child windows
- Validates window classes against known patterns
- Maps windows to target edit controls
- Determines allowed memory types per control

## Core Components

### `window_detector.py` - ClickWindowDetector

Detects Click.exe child windows and validates controls.

**Architecture:**
```python
class ClickWindowDetector:
    def __init__(self):
        self.polling_interval = 100  # ms
        self.current_window = None
        self.current_control = None

    def start_polling(self):
        """Begin polling for Click windows."""
        self._poll()

    def _poll(self):
        """Poll for Click windows every 100ms."""
        window = self._find_click_window()
        if window != self.current_window:
            self.on_window_changed(window)
        self.root.after(self.polling_interval, self._poll)
```

**Detection Flow:**
1. Enumerate all top-level windows
2. Filter for visible windows
3. Check process name == "Click.exe"
4. Validate window class against known patterns
5. Find target edit control in window hierarchy
6. Determine allowed memory types

**Window Detection:**
```python
def _find_click_window(self) -> int | None:
    """Find active Click instruction dialog."""
    for hwnd in win32_utils.enum_windows():
        if not win32_utils.is_window_visible(hwnd):
            continue

        # Check process name
        process_name = win32_utils.get_process_name(hwnd)
        if process_name.lower() != "click.exe":
            continue

        # Check window class
        class_name = win32_utils.get_class_name(hwnd)
        if class_name in KNOWN_WINDOW_CLASSES:
            return hwnd

    return None
```

**Control Detection:**
```python
def _find_target_control(self, parent_hwnd: int) -> int | None:
    """Find target edit control in window."""
    # Get window class
    class_name = win32_utils.get_class_name(parent_hwnd)

    # Lookup control mapping
    mapping = WINDOW_MAPPINGS.get(class_name)
    if not mapping:
        return None

    # Find control by class and position
    children = win32_utils.enum_child_windows(parent_hwnd)
    for child in children:
        child_class = win32_utils.get_class_name(child)
        if child_class == mapping["control_class"]:
            # Validate control position/size
            if self._validate_control(child, mapping):
                return child

    return None
```

**Control Validation:**
```python
def _validate_control(self, hwnd: int, mapping: dict) -> bool:
    """Validate control meets expected criteria."""
    rect = win32_utils.get_window_rect(hwnd)
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]

    # Check minimum size
    if width < mapping.get("min_width", 0):
        return False
    if height < mapping.get("min_height", 0):
        return False

    # Check control is editable
    style = win32_utils.get_window_style(hwnd)
    if style & win32con.ES_READONLY:
        return False

    return True
```

### `window_mapping.py` - Window Mapping Configuration

Maps CLICK window classes to edit controls and allowed address types.

**Mapping Structure:**
```python
WINDOW_MAPPINGS = {
    # Contact/Coil Instructions (X, Y, C, T, CT)
    "TCoilInstruction": {
        "control_class": "Edit",
        "control_id": 1001,
        "allowed_types": {"X", "Y", "C", "T", "CT"},
        "min_width": 50,
        "min_height": 20
    },

    # Timer/Counter Instructions (T, TD, CT, CTD)
    "TTimerInstruction": {
        "control_class": "Edit",
        "control_id": 1002,
        "allowed_types": {"T", "TD", "CT", "CTD"},
        "min_width": 50,
        "min_height": 20
    },

    # Data Instructions (DS, DD, DH, DF, XD, YD, SD, TXT)
    "TDataInstruction": {
        "control_class": "Edit",
        "control_id": 1003,
        "allowed_types": {"DS", "DD", "DH", "DF", "XD", "YD", "SD", "TXT"},
        "min_width": 50,
        "min_height": 20
    },

    # Compare Instructions (all types)
    "TCompareInstruction": {
        "control_class": "Edit",
        "control_id": 1004,
        "allowed_types": {"X", "Y", "C", "T", "TD", "CT", "CTD", "SC", "DS", "DD", "DH", "DF", "XD", "YD", "SD"},
        "min_width": 50,
        "min_height": 20
    },

    # Math Instructions (data types only)
    "TMathInstruction": {
        "control_class": "Edit",
        "control_id": 1005,
        "allowed_types": {"DS", "DD", "DH", "DF", "XD", "YD", "SD"},
        "min_width": 50,
        "min_height": 20
    },

    # Copy/Move Instructions (all types)
    "TCopyInstruction": {
        "control_class": "Edit",
        "control_id": 1006,
        "allowed_types": {"X", "Y", "C", "T", "TD", "CT", "CTD", "SC", "DS", "DD", "DH", "DF", "XD", "YD", "SD", "TXT"},
        "min_width": 50,
        "min_height": 20
    }
}
```

**Getting Allowed Types:**
```python
def get_allowed_types(window_class: str) -> set[str]:
    """Get allowed memory types for window class."""
    mapping = WINDOW_MAPPINGS.get(window_class)
    return mapping["allowed_types"] if mapping else set()
```

**Adding New Mappings:**
To support a new CLICK dialog:
1. Identify the window class using Spy++ or similar tool
2. Find the target edit control class and ID
3. Determine which memory types are valid for that instruction
4. Add mapping to `WINDOW_MAPPINGS`

**Example (adding a new instruction):**
```python
# New instruction discovered: TShiftInstruction
WINDOW_MAPPINGS["TShiftInstruction"] = {
    "control_class": "Edit",
    "control_id": 1007,
    "allowed_types": {"DS", "DD"},  # Only data registers
    "min_width": 50,
    "min_height": 20
}
```

## Detection Flow Details

### 1. Initial Poll

```python
# App starts polling
detector = ClickWindowDetector()
detector.start_polling()
```

### 2. Window Detection

```python
# Every 100ms
window_hwnd = detector._find_click_window()
if window_hwnd:
    class_name = win32_utils.get_class_name(window_hwnd)
    print(f"Found: {class_name}")
```

### 3. Control Detection

```python
control_hwnd = detector._find_target_control(window_hwnd)
if control_hwnd:
    allowed_types = get_allowed_types(class_name)
    print(f"Control found, allowed types: {allowed_types}")
```

### 4. Overlay Positioning

```python
if control_hwnd:
    overlay.set_target_control(control_hwnd)
    overlay.set_allowed_types(allowed_types)
    overlay.show()
else:
    overlay.hide()
```

### 5. Continuous Monitoring

```python
# Poll continues every 100ms
# If window closes or control changes:
if window_hwnd != previous_window:
    overlay.hide()
    detector.on_window_changed(window_hwnd)
```

## CLICK Version Support

ClickNick supports CLICK Programming Software v2.60–v3.80.

**Version Differences:**
- v2.60-v2.99: Older window class names (e.g., "TInstructionDialog")
- v3.00-v3.80: Updated window class names (e.g., "TCoilInstruction")

**Version Detection:**
```python
def detect_click_version() -> str:
    """Detect CLICK software version."""
    # Read version from Click.exe file properties
    exe_path = find_click_executable()
    if exe_path:
        info = win32api.GetFileVersionInfo(exe_path, "\\")
        version = f"{info['FileVersionMS'] >> 16}.{info['FileVersionMS'] & 0xFFFF}"
        return version
    return "Unknown"
```

**Compatibility Layer:**
```python
# Map old class names to new
CLASS_NAME_ALIASES = {
    "TInstructionDialog": "TCoilInstruction",  # v2.x → v3.x
    "TTimerDialog": "TTimerInstruction",
    # ...
}

def normalize_class_name(class_name: str) -> str:
    """Normalize class name for version compatibility."""
    return CLASS_NAME_ALIASES.get(class_name, class_name)
```

## Performance Considerations

**Polling Interval:**
- 100ms default (responsive, low CPU usage)
- Too fast: Higher CPU usage
- Too slow: Delayed overlay appearance

**Window Enumeration:**
- Enumerate only visible windows (skip hidden)
- Cache process names (avoid repeated lookups)
- Early exit when Click window found

**Control Validation:**
- Validate control only when window changes
- Cache validated controls
- Invalidate cache on window close

## Error Handling

**Window Detection Errors:**
```python
try:
    hwnd = win32_utils.enum_windows()
except win32gui.error as e:
    logger.error(f"Window enumeration failed: {e}")
    # Continue polling (window may have closed)
```

**Control Access Errors:**
```python
try:
    rect = win32_utils.get_window_rect(control_hwnd)
except win32gui.error:
    # Control no longer valid
    self.current_control = None
    overlay.hide()
```

**Process Name Errors:**
```python
try:
    process_name = win32_utils.get_process_name(hwnd)
except Exception:
    # Process may have terminated
    return None
```

## Debugging

**Enable Detection Logging:**
```python
detector = ClickWindowDetector()
detector.enable_debug_logging(True)

# Logs:
# [DEBUG] Polling...
# [DEBUG] Found window: TCoilInstruction (hwnd=12345)
# [DEBUG] Found control: Edit (hwnd=67890)
# [DEBUG] Allowed types: {'X', 'Y', 'C'}
```

**Spy++ Integration:**
- Use Spy++ to inspect CLICK windows
- Identify window class names
- Find control class and ID
- Verify window hierarchy

## Testing

Detection tests are in `tests/test_detection/`:
- `test_window_detector.py` - Window/control detection logic
- `test_window_mapping.py` - Mapping configuration
- Detection tests use mocked Win32 API calls (no actual CLICK required)
