# ClickNick

![clicknick_logo](https://github.com/user-attachments/assets/2cb7f411-3174-478c-a6c9-409aaa788376)

*Modern IDE Features for Automation Direct CLICK PLC Programming.*
  
ClickNick adds autocomplete, bulk editing, and visual organization tools to CLICK Programming Software.

| | Standard CLICK | ClickNick |
|---|---|---|
| **Instruction Entry** | Type addresses `C123` | ✅ **Autocomplete** nicknames |
| **Address Editing** | One-by-one in app | ✅ **Bulk edit**, multi-window, search/replace |
| **Organization** | Flat list | ✅ **Color named blocks** + **tree outline** (hierarchy & arrays) |
| **DataView** | Input raw addresses, limited reordering | ✅ **Autocomplete**, add entire grouped structures and blocks, drag and drop reordering |
| **Price** | Free (bundled) | Free (open source) |
| **Best For** | Simple projects | Complex projects, productivity |

## Features at a Glance

- **[✨ Nickname Autocomplete](#autocomplete)** – Type `Valve5` instead of `C123`, with smart filters and hover tooltips
- **[🛠️ Modern Address Editor](#address-editor)** – Bulk edit with search/replace, color-coded blocks, multi-window support
- **[📑 Navigation Dock](#navigation-dock)** – Tree view with automatic hierarchy and array grouping
- **[📊 Dataview Editor](#dataview-editor)** – Tabbed interface, nickname lookup, unlimited reordering
- **[🔌 Connectivity](#connectivity)** – CSV import and live ODBC database support

**Beta Disclaimer** – This is beta software. Use at your own risk and always back up `.ckp` files.

---

## Prerequisites

- **OS:** Windows 10 or 11
- **CLICK Software:** v2.60–v3.80 ([download here](https://www.automationdirect.com/clickplcs/free-software/free-click-software))
- **ODBC Drivers:** Microsoft Access Database Engine (for live DB connection; [install link](https://github.com/ssweber/clicknick/issues/17))
- **Python:** 3.11+ (only if using pip; uv manages Python automatically)

## Quick Start

### Option 1: uv (recommended)
```bash
uvx clicknick@latest              # Try it without installing
uv tool install clicknick         # Install for offline use
clicknick                         # Run (command line or Start Menu)
```
New to uv? See [installation instructions](https://github.com/astral-sh/uv#installation).  

### Option 2: pip
```bash
pip install clicknick
python -m clicknick
```

---

## Detailed Features

### <a name="autocomplete"></a>✨ Nickname Autocomplete

Skip the addresses – Select Valve5 instead of typing C123  
Flexible filters – Prefix, partial match/contains, or abbreviation (e.g., Motor Speed ↔ Mtr_Spd)  
Hover tooltips – View address comments at a glance  
Exclusion filters – Hide system or internal addresses (e.g., SC/SD, __private__)

![ClickNick autocomplete demo](https://github.com/user-attachments/assets/0275dcf4-6d79-4775-8763-18b13e8fd3a3)  

---

### <a name="address-editor"></a>🛠️ Modern Address Editor

Multi-window – Edit different address sections simultaneously  
Bulk editing – Edit before saving, copy/paste multiple cells, live duplicate detection and validation  
Search & Replace (Ctrl+F / Ctrl+R) - With Find in Selection toggle  
Custom blocks – Drag to create color-coded groups for organization and quick navigation

> [!NOTE]  
> Nicknames edited in the Address Editor appear immediately in autocomplete. 
> Existing ladder logic refreshes after editing via the built-in Address Picker (Ctrl+T) or reopening the project.  
> See issue https://github.com/ssweber/clicknick/issues/36

> **⚠️ Search & Replace Behavior**  
> Replace affects all *visible* columns. Hidden columns (Initial Value, Retentive) are only modified if you make them visible first. Use "Find in Selection" to limit scope.

![Address Editor demo](https://github.com/user-attachments/assets/4aa6fd2f-f6f8-4921-aba3-7f16e51b95ce)  

---

### <a name="navigation-dock"></a>📑 Navigation Dock

Navigate large projects – See all your nicknames in an organized tree view  
Spot patterns – Arrays and related items grouped automatically  

**Hierarchy:** Single underscores create levels. `SupplyTank_Pump_Status` becomes:
```
SupplyTank
    └── Pump
        └── Status
```

**Arrays:** Trailing numbers auto-group. `Alm1_id`, `Alm1_value`, `Alm2_id`, `Alm2_value` becomes:
```
Alm[1-2]
1
  ├── id
  └── value
2
  ├── id
  └── value
```

One-click access – Double-click any item to edit.

![Outline dock screenshot](https://github.com/user-attachments/assets/07928355-180e-4b00-b0bb-07ad2bdbe831)

---

### <a name="dataview-editor"></a>📊 Dataview Editor

Project integration – Loads all DataViews (.cdv files) from your CLICK project in tab-interface  
Nickname lookup – Add addresses by typing nicknames instead of raw addresses  
Drag-and-drop reordering – Rearrange rows freely with cut/paste support  
Flexible row limit – No hard 100-row limit while organizing; overflow rows shown in grey (excluded from save)  
Navigator integration – Double-click nicknames or entire structures from the Outline/Blocks panel to insert

---

### <a name="connectivity"></a>🔌 Connectivity

- **CSV nickname import** – No drivers needed. Import from any spreadsheet
- **Live ODBC database connection** – Direct, real-time access to CLICK project database

---

## Block Tag Specification

> **Note:** The Address Editor provides buttons to create and manage blocks. This section documents the underlying format for power users.

Add tags in the Comment field to create visual blocks:

**Syntax:**
- `<BlockName>` - Opening tag for a range
- `</BlockName>` - Closing tag for a range
- `<BlockName />` - Self-closing tag for a singular point
- `<BlockName bg="#color">` - Adds background color

**Colors:** Use HEX codes or keywords: Red, Pink, Purple, Deep Purple, Indigo, Blue, Light Blue, Cyan, Teal, Green, Light Green, Lime, Yellow, Amber, Orange, Deep Orange, Brown, Blue Grey

Example: `<Alm Bits bg="Red">` ... `</Alm Bits>`

---

## Motivation

CLICK PLCs were my first PLC experience, but remembering addresses became painful. Other platforms autocomplete—why not CLICK? ClickNick adds the modern tools I wish I'd had.

---

## **Documentation**  

- [Installation Guide](installation.md) – Python and uv setup  
- [Development](development.md) – Contributing workflows  
- [Publishing](publishing.md) – PyPI release instructions  

---

*This project was built from
[simple-modern-uv](https://github.com/jlevy/simple-modern-uv).*

