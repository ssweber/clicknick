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

![Address Editor](https://github.com/user-attachments/assets/REPLACE_WITH_ACTUAL_SCREENSHOT)  

> [!NOTE]  
> Nicknames edited in the Address Editor appear immediately in autocomplete. Existing ladder logic refreshes after editing via the built-in Address Picker (Ctrl+T) or reopening the project.  
  
## **Why ClickNick?**    
✔ **Work faster** – Less time on manual address lookup  
✔ **Fewer mistakes** – Autocomplete reduces typos  
✔ **Stay organized** – Better tag management for complex projects  

## **Connectivity**  
- 🔌 Live ODBC database connection  
- 📄 CSV nickname import  

---

## **Installation**  

> [!NOTE]  
> Live database connectivity requires Microsoft Access ODBC drivers. See our [installation guide](https://github.com/ssweber/clicknick/issues/17) if you encounter driver issues. CSV import works without additional drivers.  

### Option 1: uv (recommended)  

**Try it:**  
```cmd  
uvx clicknick@latest  
```  

**Install for offline use:**  
```cmd  
uv tool install clicknick  
```  

**Run:** `clicknick` (command line or Start Menu)  
**Upgrade:** `uv tool upgrade clicknick`  
**Uninstall:** `uv tool uninstall clicknick`  

New to uv? See [installation instructions](https://github.com/astral-sh/uv#installation).  

### Option 2: pip  

```cmd  
pip install clicknick  
python -m clicknick  
```  

---

## **Usage**  

1. Open your CLICK Programming Software project  
2. Launch ClickNick to enable autocomplete in address input fields  
3. Use **Tools → Address Editor** for advanced tag management  

---

## **Requirements**  

- Windows 10/11  
- CLICK Programming Software (v2.60–v3.71)  
- Microsoft Access ODBC drivers (for Address Editor)  

---

## **Supported Windows**  

Autocomplete works in:  

| Instructions | Dialogs & Tools |
|--------------|-----------------|
| Contact (NO/NC) | Search & Replace |
| Edge Contact | Data Views |
| Out, Set, Reset | Address Picker Find |
| Compare (A with B) | Modbus Send/Receive |
| Timer, Counter | |
| Math | |
| Shift Register | |
| Copy | |
| Search | |

---

## **Documentation**  

- [Installation Guide](installation.md) – Python and uv setup  
- [Development](development.md) – Contributing workflows  
- [Publishing](publishing.md) – PyPI release instructions  

---

*This project was built from
[simple-modern-uv](https://github.com/jlevy/simple-modern-uv).*

