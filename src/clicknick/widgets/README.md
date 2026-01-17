# Widgets Module

This module contains reusable UI components used across ClickNick windows and dialogs.

## Overview

Widgets are self-contained UI components that can be reused in multiple contexts:
- Custom autocomplete combobox with keyboard navigation
- Floating tooltips for nickname details
- Dialogs for adding blocks, creating tabs, etc.
- Custom notebook with closeable tabs
- Character limit indicators

## Core Widgets

### `nickname_combobox.py` - NicknameCombobox

Custom autocomplete combobox with keyboard navigation.

**Features:**
- Filtered dropdown based on typed text
- Arrow key navigation (Up/Down)
- Enter to select
- Escape to cancel
- Auto-complete on Tab
- Case-insensitive matching

**Usage:**
```python
combobox = NicknameCombobox(
    parent,
    values=["StartButton", "StopButton", "AlarmLight"],
    on_select=self.on_nickname_selected
)
combobox.pack()

def on_nickname_selected(self, value: str):
    print(f"Selected: {value}")
```

**Keyboard Navigation:**
- Type → filters list
- Up/Down → navigate filtered results
- Enter → select highlighted item
- Tab → auto-complete with first match
- Escape → clear selection

**Implementation Details:**
```python
class NicknameCombobox(ttk.Combobox):
    def __init__(self, parent, values, on_select=None):
        super().__init__(parent, values=values)
        self.bind("<KeyRelease>", self._on_key_release)
        self.bind("<Return>", self._on_return)
        self.bind("<Escape>", self._on_escape)
        self.bind("<Up>", self._on_up)
        self.bind("<Down>", self._on_down)

    def _on_key_release(self, event):
        """Filter values based on typed text."""
        typed = self.get().lower()
        filtered = [v for v in self._all_values if typed in v.lower()]
        self.config(values=filtered)
```

### `floating_tooltip.py` - FloatingTooltip

Shows nickname details on hover.

**Features:**
- Appears on mouse hover (500ms delay)
- Shows nickname, address, comment
- Disappears on mouse leave
- Auto-positioning (avoids screen edges)

**Usage:**
```python
tooltip = FloatingTooltip(
    widget,
    get_text=lambda: self.get_nickname_details()
)

def get_nickname_details(self):
    return f"Address: X001\nNickname: StartButton\nComment: Main start button"
```

**Example:**
```
┌──────────────────────────┐
│ Address: X001            │
│ Nickname: StartButton    │
│ Comment: Main start btn  │
└──────────────────────────┘
```

### `prefix_autocomplete.py` - PrefixAutocomplete

Prefix-based autocomplete logic for entry widgets.

**Features:**
- Real-time filtering as user types
- Prefix matching (not substring)
- Dropdown list of matches
- Tab to cycle through matches

**Usage:**
```python
entry = tk.Entry(parent)
autocomplete = PrefixAutocomplete(
    entry,
    get_completions=lambda: ["StartButton", "StopButton", "StatusLight"]
)
```

**Behavior:**
- User types "St" → shows ["StartButton", "StopButton", "StatusLight"]
- User types "Sta" → shows ["StartButton", "StatusLight"]
- Tab → cycle through matches

### `add_block_dialog.py` - AddBlockDialog

Dialog for adding address blocks with block tags.

**Features:**
- Input block name
- Select background color (color picker or presets)
- Preview block tag syntax
- Validate block name

**Usage:**
```python
dialog = AddBlockDialog(parent)
result = dialog.show()

if result:
    block_name = result["name"]
    bg_color = result["color"]
    # Insert <BlockName bg="color"> into comment
```

**Dialog Layout:**
```
┌─────────────────────────────┐
│ Add Block                   │
├─────────────────────────────┤
│ Block Name: [_____________] │
│                             │
│ Background Color:           │
│ ○ Red   ○ Blue   ○ Green   │
│ ○ Yellow ○ Purple ○ Custom  │
│                             │
│ Preview: <MyBlock bg="Red"> │
│                             │
│      [Cancel]  [Add Block]  │
└─────────────────────────────┘
```

### `new_tab_dialog.py` - NewTabDialog

Dialog for creating new tabs in Address Editor.

**Features:**
- Option to clone current tab state
- Option to start fresh
- Preview of what will be cloned

**Usage:**
```python
dialog = NewTabDialog(parent, current_state=current_tab_state)
result = dialog.show()

if result == "clone":
    # Clone current tab
elif result == "fresh":
    # Start fresh
```

**Dialog Layout:**
```
┌─────────────────────────────────┐
│ New Tab                         │
├─────────────────────────────────┤
│ ○ Clone current tab             │
│   • Filter: "pump"              │
│   • Hide empty: Yes             │
│   • Scroll position: X section  │
│                                 │
│ ○ Start fresh                   │
│   • No filters                  │
│   • Show all rows               │
│                                 │
│      [Cancel]      [Create]     │
└─────────────────────────────────┘
```

### `custom_notebook.py` - CustomNotebook

ttk.Notebook with closeable tabs.

**Features:**
- Close button on each tab
- Middle-click to close tab
- Ctrl+W to close current tab
- Prevent closing last tab
- Tab reordering (drag-and-drop)

**Usage:**
```python
notebook = CustomNotebook(parent)
notebook.add_tab(panel, text="Tab 1", closeable=True)

def on_tab_closed(tab_id):
    print(f"Tab {tab_id} closed")

notebook.bind("<<TabClosed>>", lambda e: on_tab_closed(notebook.tab_id))
```

**Tab Rendering:**
```
┌─────────┬─────────┬─────────┐
│ Tab 1 ✕ │ Tab 2 ✕ │ Tab 3 ✕ │
└─────────┴─────────┴─────────┘
```

**Close Button Behavior:**
- Click ✕ → close tab
- Middle-click tab → close tab
- Ctrl+W → close current tab
- Last tab cannot be closed

### `char_limit_tooltip.py` - CharLimitTooltip

Character limit indicator for entry widgets.

**Features:**
- Shows remaining characters
- Changes color as limit approaches
- Prevents over-limit input (optional)
- Visual feedback (green → yellow → red)

**Usage:**
```python
entry = tk.Entry(parent)
limit_tooltip = CharLimitTooltip(entry, max_chars=20)

# Binds to entry, shows "15/20" as user types
```

**Visual States:**
```
0-60% full:   [15/20]  (green)
60-90% full:  [18/20]  (yellow)
90-100% full: [20/20]  (red)
```

**Example in Nickname Field:**
```
Nickname: [StartButton_____] 15/20
```

### `colors.py` - Color Constants

Centralized color definitions for the editor UI.

**Color Palette:**
```python
# Validation colors
ERROR_BG = "#FFF3CD"
ERROR_FG = "#856404"

# Dirty tracking
DIRTY_BG = "#D1ECF1"

# Block colors (Material Design palette)
BLOCK_COLORS = {
    "Red": "#F44336",
    "Pink": "#E91E63",
    "Purple": "#9C27B0",
    "Deep Purple": "#673AB7",
    "Indigo": "#3F51B5",
    "Blue": "#2196F3",
    "Light Blue": "#03A9F4",
    "Cyan": "#00BCD4",
    "Teal": "#009688",
    "Green": "#4CAF50",
    "Light Green": "#8BC34A",
    "Lime": "#CDDC39",
    "Yellow": "#FFEB3B",
    "Amber": "#FFC107",
    "Orange": "#FF9800",
    "Deep Orange": "#FF5722",
    "Brown": "#795548",
    "Blue Grey": "#607D8B"
}
```

## Dialog Components

### `dialogs.py` - About and ODBC Warning Dialogs

**About Dialog:**
```python
def show_about_dialog(parent):
    """Show About ClickNick dialog."""
    dialog = tk.Toplevel(parent)
    dialog.title("About ClickNick")

    label = tk.Label(dialog, text=(
        "ClickNick v1.0\n"
        "Context-aware nickname autocomplete\n"
        "for CLICK PLC Programming Software"
    ))
    label.pack(padx=20, pady=20)
```

**ODBC Warning Dialog:**
```python
def show_odbc_warning_dialog(parent, error: str = None):
    """Show ODBC driver warning."""
    dialog = tk.Toplevel(parent)
    dialog.title("ODBC Driver Required")

    message = (
        "Microsoft Access Database Engine required.\n\n"
        "Download from:\n"
        "https://www.microsoft.com/en-us/download/details.aspx?id=54920"
    )

    if error:
        message += f"\n\nError: {error}"

    label = tk.Label(dialog, text=message)
    label.pack(padx=20, pady=20)
```

## Widget Composition Patterns

### Combining Widgets

Widgets are designed to be composed together:

```python
class AddressInputPanel(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        # Nickname entry with autocomplete and char limit
        self.nickname_entry = tk.Entry(self)
        self.nickname_autocomplete = PrefixAutocomplete(
            self.nickname_entry,
            get_completions=self.get_nickname_completions
        )
        self.char_limit = CharLimitTooltip(self.nickname_entry, max_chars=20)

        # Tooltip on hover
        self.tooltip = FloatingTooltip(
            self.nickname_entry,
            get_text=self.get_tooltip_text
        )
```

### Event Handling

Widgets communicate via callbacks:

```python
# Widget provides callback parameter
combobox = NicknameCombobox(
    parent,
    values=nicknames,
    on_select=self.on_nickname_selected  # Callback
)

def on_nickname_selected(self, value: str):
    # Handle selection
    self.insert_nickname(value)
```

## Testing

Widget tests are in `tests/test_widgets/`:
- `test_nickname_combobox.py` - Keyboard navigation, filtering
- `test_floating_tooltip.py` - Positioning, timing, content
- `test_custom_notebook.py` - Tab closing, reordering
- Widget tests require tkinter (run in headless CI with Xvfb)
