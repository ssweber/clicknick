![clicknick_logo](https://github.com/user-attachments/assets/2cb7f411-3174-478c-a6c9-409aaa788376)

# **ClickNick**  
*Enhanced Productivity for CLICK PLC Programming*    
  
Add **nickname autocomplete** to CLICK Programming Software and a **modern Address Editor**.  
  
![ClickNick demo](https://github.com/user-attachments/assets/0275dcf4-6d79-4775-8763-18b13e8fd3a3)  
  
## **Features**    
  
### ✨ Nickname Autocomplete    
- **Skip the addresses** – Select `Valve5` instead of typing `C123`    
- **Flexible search** – Prefix, partial match, or abbreviation (e.g., `Motor Speed` ↔ `Mtr_Spd`)    
- **Hover tooltips** – View address comments at a glance    
- **Exclusion filters** – Hide system or internal addresses (e.g., `SC/SD`, `__private__`)    
  
### 🛠️ Modern Address Editor    
- **Multi-window** – Edit different address sections simultaneously    
- **Bulk editing** – Edit before saving, copy/paste multiple cells, live duplicate detection and validation    
- **Search & Replace** – With in-selection support (Ctrl+F / Ctrl+R)    
- **Custom blocks** – Drag to create color-coded groups for organization and quick navigation  
  
## **Why ClickNick?**    
✔ **Work faster** – Less time on manual address lookup  
✔ **Fewer mistakes** – Autocomplete reduces typos  
✔ **Stay organized** – Better tag management for complex projects  

🔌 **Connectivity Options:**  
- Live ODBC database connection  
- CSV nickname file import  

> [!NOTE]  
> Nicknames edited via the `Address Editor` appear immediately in ClickNick autocomplete and newly placed instructions. Existing ladder will refresh after editing a nickname via the built-in `Address Picker : Edit Mode` (Ctrl+T) or reopening the project.

![Address Editor](https://github.com/user-attachments/assets/REPLACE_WITH_ACTUAL_SCREENSHOT)  

## How to Run
> [!NOTE]
> For live nickname database functionality, you'll need Microsoft Access ODBC drivers installed. If you see an "ODBC drivers not found" warning, see our [installation guide](https://github.com/ssweber/clicknick/issues/17) for help. CSV nickname file loading works without these drivers.

### Option 1: Using uv (recommended)
**Try it out:**
```cmd
uvx clicknick@latest
```

**Install for offline use:**
```cmd
uv tool install clicknick
```

**Run:** `clicknick` (from command line or Start Menu)

**Uninstall:** `uv tool uninstall clicknick`  
**Upgrade:** `uv tool upgrade clicknick`

If you don't have uv: https://github.com/astral-sh/uv#installation

### Option 2: Using pip
```cmd
pip install clicknick
python -m clicknick
```

## Usage

1. Open CLICK Programming Software project.
2. Launch ClickNick to add Auto-Complete to where you typically enter Memory Addresses.
3. Open Tools -> Address Editor for advanced tag management with full search, filtering, and bulk editing capabilities

## Requirements

- Windows 10 or 11
- CLICK Programming Software (v2.60 – v3.71).
- Address Editor requires Microsoft Access ODBC drivers

## Auto-Complete Supported Windows

- Contact Normally Open/Closed
- Edge Contact
- Out, Set, Reset
- Compare (A with B)
- Timer, Counter
- Math instructions
- Shift Register
- Copy instruction
- Search instruction
- Search & Replace dialogs
- Data Views
- Address Picker `Find`
- Modbus Send/Receive

* * *

## Project Docs

For how to install uv and Python, see [installation.md](installation.md).

For development workflows, see [development.md](development.md).

For instructions on publishing to PyPI, see [publishing.md](publishing.md).

* * *

*This project was built from
[simple-modern-uv](https://github.com/jlevy/simple-modern-uv).*

