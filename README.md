# ClickNick

![clicknick_logo](https://github.com/user-attachments/assets/2cb7f411-3174-478c-a6c9-409aaa788376)

*Tag-Based Programming for Automation Direct CLICK PLCs.*

**ClickNick** lets you program using nicknames instead of raw memory addresses. It provides autocomplete that appears over CLICK instruction dialogs, plus standalone editors that sync with your project.

| | Standard CLICK | ClickNick |
|---|---|---|
| **Ladder Logic Editor** | Type addresses `C123` | ✅ **Autocomplete** nicknames |
| **Address Editing** | One-by-one in app | ✅ **Bulk edit**, multi-window, search/replace |
| **Tag View** | Flat list | ✅ **Color named blocks** + **tree outline** (hierarchy & arrays) |
| **DataView** | Input raw addresses, limited reordering | ✅ **Autocomplete**, add entire grouped structures and blocks, drag and drop reordering |
| **Price** | Free (bundled) | Free (open source) |
| **Best For** | Simple projects | Complex projects, productivity |

ClickNick works with your existing `.ckp` projects—just open your project in CLICK Software and connect. It's entirely local with no internet calls or telemetry; changes are temporary until you save in CLICK.

### Why ClickNick?

CLICK PLCs were my first PLC experience, but remembering addresses became painful. Other platforms autocomplete—why not CLICK? ClickNick adds the modern tools I wish I'd had.

## Features at a Glance

- **[✨ Nickname Autocomplete](#autocomplete)** – Type `Valve5` instead of `C123`, with smart filters and hover tooltips
- **[🛠️ Modern Address Editor](#address-editor)** – Bulk edit with search/replace, color-coded blocks, multi-window support
- **[📑 Tag Browser](#tag-browser)** – Tree view with automatic hierarchy and array grouping
- **[📊 Dataview Editor](#dataview-editor)** – Tabbed interface, nickname lookup, unlimited reordering
- **[🔌 Connectivity](#connectivity)** – CSV import and live ODBC database support

**Beta** – Review Address & Dataview changes before saving in CLICK. [Feedback welcome](https://github.com/ssweber/clicknick/issues).

---

## Prerequisites

- **OS:** Windows 10 or 11
- **CLICK Software:** v2.60–v3.90 ([download here](https://www.automationdirect.com/clickplcs/free-software/free-click-software))
- **ODBC Drivers:** Microsoft Access Database Engine ([install link](https://github.com/ssweber/clicknick/issues/17)) – *only needed for live DB sync; CSV import works without drivers*
- **Python:** 3.11+ (only if using pip; uv manages Python automatically)

## Quick Start

### Option 1: uv (recommended)
```bash
uvx clicknick@latest              # Try it without installing
uv tool install clicknick         # Install for offline use, upgrade with `uv tool upgrade clicknick`
clicknick                         # Run (WinKey+R `Run` or command line)
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

**How it works:** An autocomplete dropdown appears over CLICK instruction dialogs. Start typing a nickname and select from the filtered list—the address is inserted automatically.

- Skip the addresses – Select Valve5 instead of typing C123  
- Flexible filters – Prefix, partial match/contains, or abbreviation (e.g., Motor Speed ↔ Mtr_Spd)  
- Hover tooltips – View address comments at a glance  
- Exclusion filters – Hide system or internal addresses (e.g., SC/SD, `__private__`)  

![ClickNick autocomplete demo](https://github.com/user-attachments/assets/3a1cdff9-c425-46b7-8b90-4a357d43b6d3)  

---

### <a name="address-editor"></a>🛠️ Modern Address Editor

- Multi-window – Edit different address sections simultaneously
- Bulk editing – Edit before saving, copy/paste multiple cells, live duplicate detection and validation
- Fill Down – Select rows to auto-increment nicknames (e.g., `Alm1` → `Alm2`, `Alm3`...)
- Clone Structure – Replicate a pattern of nicknames (e.g., `Alm1_ID`, `Alm1_Val` → `Alm2_ID`, `Alm2_Val`...)
- Filter anchors: Use `^pattern` to match start, `pattern$` to match end, `^pattern$` for exact match
- Shortcuts: Ctrl+F (Find) / Ctrl+R (Replace)
    - Scope: Case-sensitive. Searches **Nickname** and **Comment** columns only. Supports `Find in Selection`.
    - **Regex Tips:**
        - `^` start of line, `$` end of line
        - `.*` match anything, `\d` digit, `\w` letter/number
        - `( )` captures a group to use as `\1`, `\2` in the **replacement box**
    - **Resources:** Visit [regex101.com](https://regex101.com) for real-time testing.
- Custom blocks – Drag to create color-coded groups for organization and quick navigation  

![Address Editor demo](https://github.com/user-attachments/assets/ee7b1914-2f18-483a-ace1-84c2aa8eea98)

> [!NOTE]  
> Nicknames edited in the Address Editor appear immediately in autocomplete.  
> Existing ladder logic refreshes after editing via the built-in Address Picker (Ctrl+T) or reopening the project.  
> See issue https://github.com/ssweber/clicknick/issues/36

---

### <a name="tag-browser"></a>📑 Tag Browser

- Navigate large projects – See all your nicknames in an organized tree view  
- Spot patterns – Arrays and related items grouped automatically  

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

- One-click access – Double-click any item to edit.

![Outline dock screenshot](https://github.com/user-attachments/assets/07928355-180e-4b00-b0bb-07ad2bdbe831)

---

### <a name="dataview-editor"></a>📊 Dataview Editor

- Loads all DataViews (.cdv files) from your CLICK project in tab-interface  
- Add addresses by typing nicknames instead of raw addresses  
- Drag-and-drop, cut/paste reordering  
- Double-click nicknames or entire structures from the Outline/Blocks panel to insert  

---

### <a name="connectivity"></a>🔌 Connectivity

- **CSV nickname import** – No drivers needed. Import from any spreadsheet
- **Live ODBC database connection** – Direct, real-time access to CLICK project database

---

<details>
<summary><strong>Block Tag Specification</strong> (Advanced)</summary>

> **Note:** The Address Editor provides buttons to create and manage blocks. This section documents the underlying format for power users.

Add tags in the Comment field to create visual blocks:

**Syntax:**
- `<BlockName>` - Opening tag for a range
- `</BlockName>` - Closing tag for a range
- `<BlockName />` - Self-closing tag for a singular point
- `<BlockName bg="#color">` - Adds background color

**Colors:** Use HEX codes or keywords: Red, Pink, Purple, Deep Purple, Indigo, Blue, Light Blue, Cyan, Teal, Green, Light Green, Lime, Yellow, Amber, Orange, Deep Orange, Brown, Blue Grey

Example: `<Alm Bits bg="Red">` ... `</Alm Bits>`

</details>

<details>
<summary><strong>Under the Hood</strong> (How ClickNick accesses your data)</summary>

ClickNick never modifies your `.ckp` project file directly. Instead, it works with the temporary files that CLICK Programming Software creates when you open a project:

**Address Data (MDB or CSV):**
- When you open a `.ckp` project, CLICK extracts a temporary Access database (`SC_.mdb`) containing all address information (nicknames, comments, initial values)
- With ODBC drivers: ClickNick connects directly to this database for live read/write access
- Without ODBC drivers: ClickNick reads the auto-generated `Address.csv` (a snapshot from when the project was opened—doesn't reflect changes made during the session). Alternatively, import a CSV exported from CLICK (File → Export)
- Changes via ODBC are written back to CLICK's scratchpad—they only become permanent when you save in CLICK Software

**DataView Files (CDV):**
- DataView configurations are stored as `.cdv` files (UTF-16 encoded CSV) in the project's temporary folder
- The Dataview Editor reads and writes these files directly
- New DataViews created in ClickNick must be imported manually in CLICK Software

**Tag Browser (Outline):**
- The tree view is generated dynamically by parsing nicknames—it doesn't store or modify any data
- Hierarchy is built by splitting nicknames at underscores; arrays are detected from trailing numbers

**Safety:** Close CLICK without saving to discard all changes made through ClickNick. Your original `.ckp` file remains untouched until you explicitly save.

</details>
