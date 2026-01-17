# Views Module

This module contains all UI windows and panels for ClickNick, implementing passive observer pattern.

## Overview

Views are **passive observers** that:
- Never manually refresh themselves (except on user-triggered events)
- Never modify data directly (only via `edit_session()`)
- Listen for `on_data_changed()` signals from `SharedAddressData`
- Delegate complex operations to Services
- Only read state, never manage it

## Views as Passive Observers

### The Rule: React, Don't Act

```python
# GOOD - View reacts to data changes
class AddressPanel(tk.Frame):
    def on_data_changed(self, sender, changed_indices: set[int]):
        """Called when SharedAddressData broadcasts changes."""
        if sender is self:
            return  # Don't refresh own changes
        self.refresh_rows(changed_indices)

    def on_cell_edit(self, event):
        """User edited cell - request change via edit session."""
        with self.shared_data.edit_session() as session:
            row = self.view.rows[row_index]
            row.nickname = new_value
            session.mark_changed(row)
        # Session closes → SharedData broadcasts → this panel refreshes

# BAD - View manually refreshing
class AddressPanel(tk.Frame):
    def on_cell_edit(self, event):
        row.nickname = new_value  # RuntimeError! No edit session
        self.refresh_all()  # Manual refresh breaks observer pattern
```

### Observer Registration

All views register with `SharedAddressData`:

```python
class AddressPanel(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.shared_data = None

    def register_with_shared_data(self, shared_data: SharedAddressData):
        """Register as observer."""
        self.shared_data = shared_data
        shared_data.register_observer(self)

    def on_data_changed(self, sender, changed_indices: set[int]):
        """Observer callback - refresh only changed rows."""
        if sender is self:
            return
        self.refresh_rows(changed_indices)
```

## Core View Components

### `overlay.py` - Overlay

Positions an autocomplete combobox over CLICK instruction dialog edit controls.

**Architecture:**
- `tk.Toplevel` window with always-on-top flag
- Detects target control via `ClickWindowDetector`
- Positions precisely over control using Win32 API
- Shows filtered nickname list via `NicknameManager`

**Positioning Flow:**
1. `ClickWindowDetector` finds target control hwnd
2. Get control rect: `win32_utils.get_window_rect(control_hwnd)`
3. Position overlay: `overlay.geometry(f"{width}x{height}+{left}+{top}")`
4. Update position on window move/resize

**Autocomplete Flow:**
1. User types in CLICK dialog
2. Overlay captures keypresses
3. `NicknameManager.get_filtered_nicknames()` filters by typed text
4. Combobox shows filtered results
5. User selects → `win32_utils.set_control_text()` inserts address

**Example:**
```python
overlay = Overlay(parent)
overlay.set_target_control(control_hwnd)
overlay.set_allowed_types({"X", "Y"})  # Only inputs/outputs
overlay.show()
```

### `address_editor/` - Address Editor

Unified tabbed editor for PLC addresses with search/replace, block tagging, and validation.

#### Architecture Overview

The Address Editor uses a **unified tabbed interface** where each tab displays ALL memory types in a single scrollable panel.

**Key Components:**
- `window.py` - Main AddressEditorWindow with tabbed notebook
- `panel.py` - AddressPanel (tksheet-based) displaying unified view
- `sheet.py` - AddressEditorSheet (custom tksheet Sheet subclass)
- `tab_state.py` - TabState dataclass for per-tab state
- `view_builder.py` - UnifiedView construction with section boundaries
- `jump_sidebar.py` - JumpSidebar for navigation between memory types
- `row_styler.py` - Visual styling (validation, dirty tracking, blocks)

#### Unified View Model

**UnifiedView** (in `view_builder.py`) contains **references** to skeleton `AddressRow` objects:

```python
@dataclass
class UnifiedView:
    rows: list[AddressRow]              # References to skeleton rows (not copies!)
    section_boundaries: dict[str, int]  # Memory type → start index
```

**Building Unified View:**
```python
def build_unified_view(
    shared_data: SharedAddressData,
    filter_text: str = "",
    hide_empty: bool = False,
    hide_assigned: bool = False,
    unsaved_only: bool = False
) -> UnifiedView:
    """Build unified view with all memory types."""
    rows = []
    section_boundaries = {}

    # Memory types ordered: X, Y, C, T/TD, CT/CTD, SC, DS, DD, DH, DF, XD, YD, SD, TXT
    for type_key in ORDERED_MEMORY_TYPES:
        section_boundaries[type_key] = len(rows)

        # Add rows for this type (with filtering)
        type_rows = get_rows_for_type(shared_data, type_key)
        rows.extend(filter_rows(type_rows, filter_text, hide_empty, ...))

    return UnifiedView(rows=rows, section_boundaries=section_boundaries)
```

**Key Points:**
- Combined types (T/TD, CT/CTD) interleave rows: T1, TD1, T2, TD2, ...
- `section_boundaries` maps type keys to starting row indices for navigation
- All tabs reference **same** skeleton rows, so edits visible everywhere

#### Tab State Management

Each tab has its own `TabState` tracking filter/column/scroll settings:

```python
@dataclass
class TabState:
    filter_text: str = ""
    hide_empty: bool = False
    hide_assigned: bool = False
    unsaved_only: bool = False
    show_used_column: bool = True
    show_init_value_column: bool = True
    scroll_position: tuple[int, int] = (0, 0)
```

**Tab Management:**
```python
class AddressEditorWindow(tk.Toplevel):
    def __init__(self, parent):
        self._tabs: dict[str, tuple[AddressPanel, TabState]] = {}

    def add_new_tab(self, clone_current: bool = False):
        """Add new tab (clone current state or start fresh)."""
        if clone_current:
            current_state = self._get_current_tab_state()
            new_state = copy(current_state)
        else:
            new_state = TabState()

        panel = AddressPanel(self.notebook, shared_data, new_state)
        self._tabs[tab_id] = (panel, new_state)
```

**New Tab Dialog:**
- User presses Ctrl+T
- Dialog asks: "Clone current tab" or "Start fresh"
- Clone preserves filters, column visibility, scroll position

#### JumpSidebar

Sidebar with buttons that scroll to memory type sections:

```python
class JumpSidebar(tk.Frame):
    def __init__(self, parent):
        # Create buttons for each memory type: X, Y, C, T/TD, ...
        for type_key in MEMORY_TYPES:
            btn = tk.Button(text=type_key, command=lambda k=type_key: self.jump_to(k))

    def jump_to(self, type_key: str):
        """Scroll panel to memory type section."""
        self.panel.scroll_to_section(type_key)

    def update_status_indicators(self):
        """Show modified/error counts per type."""
        for type_key, btn in self.buttons.items():
            count = count_dirty_rows(type_key)
            btn.config(text=f"{type_key} ({count})")
```

**Right-Click Menus:**
- Address-level jumps (X001, X002, ...)
- Block navigation (jump to block start/end)

#### Keyboard Shortcuts

- `Ctrl+T` - New tab
- `Ctrl+W` - Close current tab
- `Ctrl+S` - Save all changes
- `Ctrl+R` - Find/Replace
- `Ctrl+F` - Focus filter box
- `Ctrl+G` - Go to address

#### Row Styling

`row_styler.py` applies visual styling based on row state:

**Validation Errors:**
```python
def style_row(sheet: tksheet.Sheet, row_index: int, row: AddressRow):
    if row.validation_error:
        sheet.highlight_rows([row_index], bg="lightyellow", fg="red")
```

**Dirty Tracking:**
```python
def style_row(sheet: tksheet.Sheet, row_index: int, row: AddressRow):
    if row.is_dirty():
        sheet.highlight_rows([row_index], bg="lightblue")
```

**Block Colors:**
```python
def style_row(sheet: tksheet.Sheet, row_index: int, row: AddressRow):
    if row.block_color:
        sheet.highlight_rows([row_index], bg=row.block_color)
```

**Precedence:** Error > Dirty > Block Color

### `dataview_editor/` - Dataview Editor

Editor for CLICK DataView (.cdv) files with nickname lookup.

**Components:**
- `window.py` - DataviewEditorWindow with file list sidebar
- `panel.py` - DataviewPanel (tksheet-based) for editing
- `cdv_file.py` - CDV file I/O (UTF-16 CSV format)

**Architecture:**
```python
class DataviewEditorWindow(tk.Toplevel):
    def __init__(self, parent, shared_dataview: SharedDataviewData):
        self.file_list = tk.Listbox()  # Sidebar with .cdv files
        self.panel = DataviewPanel(self)

    def load_cdv_file(self, file_path: str):
        """Load CDV file into editor."""
        rows = cdv_file.read_cdv(file_path)
        self.panel.set_rows(rows)

    def save_cdv_file(self):
        """Save CDV file."""
        cdv_file.write_cdv(self.current_file, self.panel.get_rows())
```

**CDV File Format:**
- UTF-16 encoded CSV
- Columns: Address, Format, Label
- Example: `X001,INT,Start Button`

**Nickname Lookup:**
```python
def on_address_changed(self, address: str):
    """Auto-populate label from nickname."""
    nickname = self.shared_dataview.get_nickname_for_address(address)
    if nickname:
        self.panel.set_label(nickname.nickname)
```

### `nav_window/` - Tag Browser

Hierarchical navigation window that docks to parent.

**Components:**
- `window.py` - NavWindow (Tag Browser) main window
- `outline_panel.py` - Hierarchical treeview of nicknames
- `outline_logic.py` - Tree building logic
- `block_panel.py` - Block navigation panel

#### Outline Panel

Hierarchical treeview of nicknames parsed by underscore segments:

**Tree Structure:**
```
SupplyTank_Pump_Status → SupplyTank
                          └─ Pump
                             └─ Status

Alm1_id, Alm1_value    → Alm[1-2]
Alm2_id, Alm2_value       ├─ id
                          └─ value
```

**Building Tree:**
```python
def build_outline_tree(nicknames: list[Nickname]) -> TreeNode:
    """Build tree from nickname list."""
    root = TreeNode("Root")

    for nickname in nicknames:
        # Parse underscore segments
        segments = nickname.nickname.split("_")

        # Detect array pattern (trailing number)
        if segments[-1][-1].isdigit():
            # Group as array node
            pass

        # Build tree path
        current = root
        for segment in segments:
            current = current.get_or_create_child(segment)

    return root
```

**Outline Logic Details:**
- Single underscores create tree levels
- Trailing numbers auto-group into arrays
- Array ranges detected: `Alm1`, `Alm2`, `Alm3` → `Alm[1-3]`
- Collapse single-child chains: `A` > `B` > `C` → `A_B_C`
- Preserve leading underscores in names

**Navigation:**
- Click node → jump to address in Address Editor
- Double-click → rename all addresses in subtree

#### Block Panel

Block navigation from `<Block>` tags in comments:

```python
class BlockPanel(tk.Frame):
    def __init__(self, parent):
        self.tree = ttk.Treeview()
        self.populate_blocks()

    def populate_blocks(self):
        """Populate tree with block ranges."""
        block_ranges = BlockService.get_block_ranges(shared_data.all_rows)

        for block in block_ranges:
            self.tree.insert("", "end", text=block["name"], values=(
                block["start_address"],
                block["end_address"],
                block["color"]
            ))

    def on_block_clicked(self, event):
        """Jump to block in Address Editor."""
        block = self.get_selected_block()
        self.parent.jump_to_address(block["start_address"])
```

## View/Service Interaction Pattern

Views orchestrate, services execute:

```python
# View captures user intent
def on_fill_down_clicked(self):
    source_row = self.get_selected_row()
    target_rows = self.get_selected_range()

    # Delegate to service
    RowService.fill_down_rows(
        shared_data=self.shared_data,
        rows=target_rows,
        source_row=source_row
    )
    # Service handles edit session, validation, broadcast
    # This view refreshes via on_data_changed() callback
```

## Testing

View tests are integration tests in `tests/test_views/`:
- `test_address_editor.py` - Tab management, unified view, filtering
- `test_overlay.py` - Positioning, autocomplete
- `test_nav_window.py` - Tree building, array detection
- Most view tests require tkinter (run in headless CI with Xvfb)
