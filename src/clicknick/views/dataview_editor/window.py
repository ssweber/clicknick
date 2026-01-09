"""Main window for the Dataview Editor.

Provides a file list sidebar and tabbed interface for editing DataViews.
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from ...data.shared_dataview import SharedDataviewData
from ...widgets.custom_notebook import CustomNotebook
from ...widgets.new_dataview_dialog import NewDataviewDialog
from ...widgets.nickname_combobox import NicknameCombobox
from ..nav_window.window import NavWindow
from .panel import DataviewPanel

if TYPE_CHECKING:
    pass


class DataviewEditorWindow(tk.Toplevel):
    """Main window for the Dataview Editor.

    Features:
    - Left sidebar: List of CDV files in the project's DataView folder
    - Right panel: Notebook with tabs for open dataviews
    - Menu bar: File operations (New, Open, Save, Export)
    """

    def _setup_window(self) -> None:
        """Configure window properties."""
        base_title = "ClickNick Dataview Editor"
        if self.title_suffix:
            self.title(f"{base_title} - {self.title_suffix}")
        else:
            self.title(base_title)

        self.geometry("900x600")
        self.minsize(600, 400)

    def _refresh_file_list(self) -> None:
        """Refresh the file list from the dataview folder."""
        self.file_listbox.delete(0, tk.END)

        files = self.shared_data.get_cdv_files()
        for file_path in files:
            self.file_listbox.insert(tk.END, file_path.stem)

        # Store paths for lookup
        self._file_paths = files

    def _get_current_panel(self) -> DataviewPanel | None:
        """Get the currently active panel."""
        try:
            current = self.notebook.select()
            if current:
                return self.notebook.nametowidget(current)
        except tk.TclError:
            pass
        return None

    def _update_tab_title(self, panel: DataviewPanel) -> None:
        """Update the tab title for a panel."""
        for i in range(self.notebook.index("end")):
            if self.notebook.nametowidget(self.notebook.tabs()[i]) == panel:
                title = panel.name
                if panel.is_dirty:
                    title = f"*{title}"
                self.notebook.tab(i, text=title)
                break

    def _on_panel_modified(self) -> None:
        """Handle panel modification event."""
        panel = self._get_current_panel()
        if panel:
            self._update_tab_title(panel)

    def _open_dataview(self, file_path: Path) -> None:
        """Open a dataview file in a new tab.

        Args:
            file_path: Path to the CDV file
        """
        # Check if already open
        if file_path in self._open_panels:
            # Switch to existing tab
            panel = self._open_panels[file_path]
            for i in range(self.notebook.index("end")):
                if self.notebook.nametowidget(self.notebook.tabs()[i]) == panel:
                    self.notebook.select(i)
                    return
            return

        # Create new panel
        panel = DataviewPanel(
            self.notebook,
            file_path=file_path,
            on_modified=self._on_panel_modified,
            nickname_lookup=self.shared_data.lookup_nickname,
            address_normalizer=self.shared_data.normalize_address,
        )

        # Add tab
        self.notebook.add(panel, text=file_path.stem)
        self.notebook.select(panel)

        self._open_panels[file_path] = panel

    def _new_dataview(self) -> None:
        """Create a new unsaved dataview."""
        # Show dialog to get name
        dialog = NewDataviewDialog(self)
        name = dialog.show()

        if not name:
            return  # User cancelled

        panel = DataviewPanel(
            self.notebook,
            file_path=None,
            on_modified=self._on_panel_modified,
            nickname_lookup=self.shared_data.lookup_nickname,
            address_normalizer=self.shared_data.normalize_address,
            name=name,
        )

        self.notebook.add(panel, text=name)
        self.notebook.select(panel)

        self._open_panels[None] = panel  # Track with None key

    def _open_file(self) -> None:
        """Open a CDV file via file dialog."""
        initial_dir = self.shared_data.dataview_folder or Path.cwd()

        file_path = filedialog.askopenfilename(
            parent=self,
            title="Open DataView",
            initialdir=initial_dir,
            filetypes=[("DataView files", "*.cdv"), ("All files", "*.*")],
        )

        if file_path:
            self._open_dataview(Path(file_path))

    def _save_as(self) -> None:
        """Save the current dataview to a selected folder."""
        panel = self._get_current_panel()
        if not panel:
            return

        initial_dir = self.shared_data.dataview_folder or Path.cwd()

        # Use folder selection dialog
        folder_path = filedialog.askdirectory(
            parent=self,
            title="Select Folder to Save DataView",
            initialdir=initial_dir,
        )

        if folder_path:
            # Use the panel's name for the filename
            new_path = Path(folder_path) / f"{panel.name}.cdv"

            # Check if file already exists
            if new_path.exists() and new_path != panel.file_path:
                result = messagebox.askyesno(
                    "File Exists",
                    f"'{new_path.name}' already exists. Overwrite?",
                    parent=self,
                )
                if not result:
                    return

            # Update tracking
            old_path = panel.file_path
            if old_path in self._open_panels:
                del self._open_panels[old_path]

            panel.save_as(new_path)
            self._open_panels[new_path] = panel
            self._update_tab_title(panel)

            # Refresh file list if saved to dataview folder
            if (
                self.shared_data.dataview_folder
                and new_path.parent == self.shared_data.dataview_folder
            ):
                self._refresh_file_list()

    def _save_current(self) -> None:
        """Save the current dataview."""
        panel = self._get_current_panel()
        if not panel:
            return

        if panel.file_path:
            panel.save()
            self._update_tab_title(panel)
        else:
            self._save_as()

    def _export(self) -> None:
        """Export the current dataview to a new location."""
        # Same as Save As for now
        self._save_as()

    def _close_current_tab(self) -> None:
        """Close the current tab."""
        panel = self._get_current_panel()
        if not panel:
            return

        # Check for unsaved changes
        if panel.is_dirty:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                f"'{panel.name}' has unsaved changes. Save before closing?",
                parent=self,
            )
            if result is None:  # Cancel
                return
            if result:  # Yes - save
                if panel.file_path:
                    panel.save()
                else:
                    self._save_as()
                    if panel.is_dirty:  # User cancelled save dialog
                        return

        # Remove from tracking
        if panel.file_path in self._open_panels:
            del self._open_panels[panel.file_path]
        elif None in self._open_panels and self._open_panels[None] == panel:
            del self._open_panels[None]

        # Close tab
        self.notebook.forget(panel)
        panel.destroy()

    def _clear_selected_rows(self) -> None:
        """Clear selected rows in the current panel."""
        panel = self._get_current_panel()
        if not panel:
            return

        selected = panel.get_selected_rows()
        for row_idx in selected:
            panel.clear_row(row_idx)

    def _refresh_nicknames(self) -> None:
        """Refresh nicknames in all open panels."""
        for panel in self._open_panels.values():
            panel.refresh_nicknames()

    def _on_close(self) -> None:
        """Handle window close."""
        # Check for unsaved changes
        if self.has_unsaved_changes():
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                parent=self,
            )
            if result is None:  # Cancel
                return
            if result:  # Yes - save
                self.save_all()

        # Close navigation window if open
        if self._nav_window is not None:
            self._nav_window.destroy()
            self._nav_window = None

        # Unregister from shared data
        self.shared_data.unregister_window(self)

        # Destroy window
        self.destroy()

    def _refresh_navigation(self) -> None:
        """Refresh the navigation window with current data."""
        if self._nav_window is None:
            return

        address_shared = self.shared_data.address_shared_data
        if address_shared:
            self._nav_window.refresh(address_shared.all_rows)

    def _insert_addresses(self, addresses: list[tuple[str, int]]) -> None:
        """Insert addresses into the current dataview.

        Args:
            addresses: List of (memory_type, address) tuples to insert
        """
        from ...models.address_row import get_addr_key

        address_shared = self.shared_data.address_shared_data
        if not address_shared:
            return

        for memory_type, address in addresses:
            addr_key = get_addr_key(memory_type, address)
            row = address_shared.all_rows.get(addr_key)
            if row:
                if not self.add_address_to_current(row.display_address):
                    # No more empty rows available
                    break

    def _on_outline_select(self, path: str, leaves: list[tuple[str, int]]) -> None:
        """Handle outline selection from NavWindow - insert addresses into current dataview.

        For single leaf nodes: inserts one address.
        For folder nodes: inserts all child addresses.

        Args:
            path: Filter prefix (unused for dataview - we always insert)
            leaves: List of (memory_type, address) tuples
        """
        self._insert_addresses(leaves)

    def _on_block_select(self, leaves: list[tuple[str, int]]) -> None:
        """Handle block selection from NavWindow - insert all block addresses.

        For T/CT blocks, offers to include paired TD/CTD addresses (interleaved).

        Args:
            leaves: List of (memory_type, address) tuples for all addresses in the block
        """
        if not leaves:
            return

        # Check if this is a T or CT block (all addresses same type for a block)
        memory_types = {mem_type for mem_type, _ in leaves}
        paired_type_map = {"T": "TD", "CT": "CTD"}

        # If it's a T or CT block, offer to include paired type
        include_paired = False
        paired_type = None
        for mem_type in memory_types:
            if mem_type in paired_type_map:
                paired_type = paired_type_map[mem_type]
                include_paired = messagebox.askyesno(
                    "Include Paired Type",
                    f"Also insert {paired_type} addresses with this {mem_type} block?",
                    parent=self,
                )
                break  # Only one type per block

        # Build address list, interleaving if paired type requested
        if include_paired and paired_type:
            addresses_to_insert = []
            for orig_type, address in leaves:
                addresses_to_insert.append((orig_type, address))
                addresses_to_insert.append((paired_type, address))
        else:
            addresses_to_insert = list(leaves)

        self._insert_addresses(addresses_to_insert)

    def _toggle_nav(self) -> None:
        """Toggle the navigation window visibility."""
        if self._nav_window is None:
            # Create navigation window with double-click insert behavior
            self._nav_window = NavWindow(
                self,
                on_outline_select=self._on_outline_select,
                on_block_select=self._on_block_select,
            )
            self._refresh_navigation()
            self._tag_browser_var.set(True)
        elif self._nav_window.winfo_viewable():
            # Hide it
            self._nav_window.withdraw()
            self._tag_browser_var.set(False)
        else:
            # Show it
            self._refresh_navigation()
            self._nav_window.deiconify()
            self._nav_window._dock_to_parent()
            self._tag_browser_var.set(True)

    def _create_menu(self) -> None:
        """Create the menu bar."""
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)

        file_menu.add_command(
            label="New Dataview", command=self._new_dataview, accelerator="Ctrl+N"
        )
        file_menu.add_command(label="Open...", command=self._open_file, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self._save_current, accelerator="Ctrl+S")
        file_menu.add_command(label="Export...", command=self._export)
        file_menu.add_separator()
        file_menu.add_command(
            label="Close Tab", command=self._close_current_tab, accelerator="Ctrl+W"
        )
        file_menu.add_separator()
        file_menu.add_command(label="Close Window", command=self._on_close)

        # Bind keyboard shortcuts
        self.bind("<Control-n>", lambda e: self._new_dataview())
        self.bind("<Control-o>", lambda e: self._open_file())
        self.bind("<Control-s>", lambda e: self._save_current())
        self.bind("<Control-w>", lambda e: self._close_current_tab())

        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Clear Selected Rows", command=self._clear_selected_rows)
        edit_menu.add_separator()
        edit_menu.add_command(label="Refresh Nicknames", command=self._refresh_nicknames)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Refresh File List", command=self._refresh_file_list)
        view_menu.add_separator()

        # Tag Browser toggle (checkbutton)
        self._tag_browser_var = tk.BooleanVar(value=False)
        view_menu.add_checkbutton(
            label="Tag Browser",
            variable=self._tag_browser_var,
            command=self._toggle_nav,
        )

    def _open_selected(self) -> None:
        """Open the selected file from the list."""
        selection = self.file_listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        if idx < len(self._file_paths):
            self._open_dataview(self._file_paths[idx])

    def _on_file_double_click(self, event) -> None:
        """Handle double-click on file list."""
        self._open_selected()

    def _on_tab_changed(self, event) -> None:
        """Handle tab change event."""
        pass  # Could update window title, etc.

    def _on_tab_close_request(self, tab_index: int) -> bool:
        """Handle close button click on a tab.

        Args:
            tab_index: Index of the tab being closed

        Returns:
            True to allow close, False to cancel
        """
        try:
            tab_id = self.notebook.tabs()[tab_index]
            panel = self.notebook.nametowidget(tab_id)

            # Check for unsaved changes
            if panel.is_dirty:
                result = messagebox.askyesnocancel(
                    "Unsaved Changes",
                    f"'{panel.name}' has unsaved changes. Save before closing?",
                    parent=self,
                )
                if result is None:  # Cancel
                    return False
                if result:  # Yes - save
                    if panel.file_path:
                        panel.save()
                    else:
                        # Need to save as
                        self.notebook.select(tab_index)
                        self._save_as()
                        if panel.is_dirty:  # User cancelled save dialog
                            return False

            # Remove from tracking (cleanup before notebook.forget is called)
            if panel.file_path in self._open_panels:
                del self._open_panels[panel.file_path]
            elif None in self._open_panels and self._open_panels[None] == panel:
                del self._open_panels[None]

            return True

        except (tk.TclError, IndexError):
            return True

    def _on_tab_closed(self, event) -> None:
        """Handle tab closed event (after the tab is removed)."""
        pass  # Cleanup already done in _on_tab_close_request

    def _close_tab_at_index(self, tab_index: int) -> None:
        """Close the tab at the given index.

        Args:
            tab_index: Index of the tab to close
        """
        try:
            tab_id = self.notebook.tabs()[tab_index]
            panel = self.notebook.nametowidget(tab_id)

            # Check for unsaved changes
            if panel.is_dirty:
                result = messagebox.askyesnocancel(
                    "Unsaved Changes",
                    f"'{panel.name}' has unsaved changes. Save before closing?",
                    parent=self,
                )
                if result is None:  # Cancel
                    return
                if result:  # Yes - save
                    if panel.file_path:
                        panel.save()
                    else:
                        # Need to save as
                        self.notebook.select(tab_index)
                        self._save_as()
                        if panel.is_dirty:  # User cancelled save dialog
                            return

            # Remove from tracking
            if panel.file_path in self._open_panels:
                del self._open_panels[panel.file_path]
            elif None in self._open_panels and self._open_panels[None] == panel:
                del self._open_panels[None]

            # Close tab
            self.notebook.forget(panel)
            panel.destroy()
        except (tk.TclError, IndexError):
            pass

    def _on_tab_right_click(self, event) -> None:
        """Handle right-click on notebook tab - show close menu."""
        # Identify which tab was clicked
        try:
            clicked_tab = self.notebook.identify(event.x, event.y)
            if clicked_tab != "label":
                return

            # Get the tab index at the click position
            tab_index = self.notebook.index(f"@{event.x},{event.y}")
            if tab_index is None:
                return

            # Create context menu
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label="Close", command=lambda: self._close_tab_at_index(tab_index))
            menu.post(event.x_root, event.y_root)
        except tk.TclError:
            pass

    def _provide_filtered_nicknames(self, search_text: str) -> list[str]:
        """Data provider for the NicknameCombobox.

        Args:
            search_text: The current search text from the combobox

        Returns:
            List of matching nickname strings
        """
        address_shared = self.shared_data.address_shared_data
        if not address_shared:
            return []

        search_upper = search_text.strip().upper()

        # Build list of matching nicknames
        matches = []
        for row in address_shared.all_rows.values():
            nickname = row.nickname
            if not nickname:
                continue

            # Match against nickname (contains search)
            if search_upper:
                if search_upper in nickname.upper():
                    matches.append(nickname)
            else:
                matches.append(nickname)

        # Sort and return
        matches.sort()
        return matches

    def _on_nickname_selected(self, nickname: str) -> None:
        """Handle nickname selection from combobox.

        Looks up the address for the nickname and inserts it into the dataview.

        Args:
            nickname: The selected nickname string
        """
        if not nickname:
            return

        address_shared = self.shared_data.address_shared_data
        if not address_shared:
            return

        # Find the address for this nickname
        for row in address_shared.all_rows.values():
            if row.nickname == nickname:
                self.add_address_to_current(row.display_address)
                self.nickname_combo.reset()
                return

        # Nickname not found - maybe user typed an address directly?
        # Try to add it as-is (will be validated by the panel)
        self.add_address_to_current(nickname)
        self.nickname_combo.reset()

    def _on_insert_button_clicked(self) -> None:
        """Handle Insert button click - finalize current combobox entry."""
        self.nickname_combo.finalize_entry()

    def _create_widgets(self) -> None:
        """Create the main UI widgets."""
        # Main paned window for sidebar + content
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Left sidebar: File list
        sidebar = ttk.Frame(self.paned)
        self.paned.add(sidebar, weight=0)

        ttk.Label(sidebar, text="Project DataViews", font=("TkDefaultFont", 10, "bold")).pack(
            pady=(5, 2), padx=5, anchor=tk.W
        )

        # File listbox with scrollbar
        list_frame = ttk.Frame(sidebar)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.file_listbox = tk.Listbox(list_frame, width=20)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Double-click to open
        self.file_listbox.bind("<Double-1>", self._on_file_double_click)

        # Buttons below file list
        btn_frame = ttk.Frame(sidebar)
        btn_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        ttk.Button(btn_frame, text="New", command=self._new_dataview, width=7).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Open", command=self._open_selected, width=7).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="⟳", command=self._refresh_file_list, width=2).pack(
            side=tk.LEFT, padx=2
        )

        # Right panel: Notebook with tabs
        self.content = ttk.Frame(self.paned)
        self.paned.add(self.content, weight=1)

        # Top toolbar with nickname combobox and insert button
        toolbar = ttk.Frame(self.content)
        toolbar.pack(fill=tk.X, padx=5, pady=(5, 0))

        # Nickname entry with NicknameCombobox
        ttk.Label(toolbar, text="Nickname:").pack(side=tk.LEFT, padx=(0, 5))

        # Frame to hold combobox (NicknameCombobox calls master.withdraw())
        self.combobox_frame = ttk.Frame(toolbar)
        self.combobox_frame.pack(side=tk.LEFT, padx=(0, 5))
        # Add dummy withdraw method since Frame doesn't have one
        self.combobox_frame.withdraw = lambda: None

        self.nickname_combo = NicknameCombobox(self.combobox_frame, width=30)
        self.nickname_combo.pack()

        # Configure the combobox callbacks
        self.nickname_combo.set_data_provider(self._provide_filtered_nicknames)
        self.nickname_combo.set_selection_callback(self._on_nickname_selected)

        # Insert button
        ttk.Button(toolbar, text="Insert", command=self._on_insert_button_clicked, width=8).pack(
            side=tk.LEFT, padx=(0, 5)
        )

        # Notebook for tabs (with close buttons)
        self.notebook = CustomNotebook(self.content, on_close_callback=self._on_tab_close_request)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # Bind tab change and close events
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.notebook.bind("<<NotebookTabClosed>>", self._on_tab_closed)
        self.notebook.bind("<Button-3>", self._on_tab_right_click)

        # Initial sash position (sidebar width)
        self.after(100, lambda: self.paned.sashpos(0, 180))

    @staticmethod
    def _get_dataview_editor_popup_flag() -> Path:
        """Get path to the flag indicating the Dataview Editor popup has been seen."""
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "ClickNick" / "dataview_editor_popup_seen"

    def _show_dataview_editor_popup(self) -> None:
        """Show first-run tips for the Dataview Editor (appears once per user)."""
        flag_path = self._get_dataview_editor_popup_flag()

        if flag_path.exists():
            return

        # Content
        popup_text = (
            "Dataview Editor (Beta)\n\n"
            "This tool edits .cdv files in CLICK's temporary project folder.\n"
            "Changes are temporary until you save in CLICK Software.\n\n"
            "Note: New Dataviews created here must be imported manually in CLICK.\n"
            "Tip: Close CLICK without saving to undo all changes."
        )

        messagebox.showinfo("First-Time Tips", popup_text, parent=self)

        # Mark as shown so we don't bother the user again
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch()

    def __init__(
        self,
        parent: tk.Widget,
        shared_data: SharedDataviewData,
        title_suffix: str = "",
    ):
        """Initialize the Dataview Editor window.

        Args:
            parent: Parent widget (usually the main app window)
            shared_data: SharedDataviewData for managing dataviews
            title_suffix: Optional suffix for window title (e.g., project name)
        """
        super().__init__(parent)

        self.shared_data = shared_data
        self.title_suffix = title_suffix

        # Track open panels by file path
        self._open_panels: dict[Path | None, DataviewPanel] = {}
        self._untitled_counter = 0

        # Navigation window
        self._nav_window: NavWindow | None = None

        # Configure window
        self._setup_window()
        self._create_menu()
        self._create_widgets()

        # Register with shared data
        shared_data.register_window(self)

        # Refresh file list
        self._refresh_file_list()

        # Show first-run popup
        self._show_dataview_editor_popup()

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Open Tag Browser by default
        self.after(100, self._toggle_nav)

    def refresh_nicknames_from_shared(self) -> None:
        """Called by SharedDataviewData when SharedAddressData changes.

        Auto-refreshes nicknames in all open panels when address data is modified.
        """
        self._refresh_nicknames()
        self._refresh_navigation()

    def has_unsaved_changes(self) -> bool:
        """Check if any open dataviews have unsaved changes."""
        return any(panel.is_dirty for panel in self._open_panels.values())

    def save_all(self) -> None:
        """Save all open dataviews that have file paths."""
        for panel in self._open_panels.values():
            if panel.file_path and panel.is_dirty:
                panel.save()
                self._update_tab_title(panel)

    def add_address_to_current(self, address: str) -> bool:
        """Add an address to the currently active dataview.

        Args:
            address: The address to add

        Returns:
            True if added successfully
        """
        panel = self._get_current_panel()
        if panel:
            return panel.add_address(address)
        return False
