![clicknick_logo](https://github.com/user-attachments/assets/2cb7f411-3174-478c-a6c9-409aaa788376)

# **ClickNick**  
*Enhanced Productivity for CLICK PLC Programming*    
  
Bolts nickname autocomplete onto CLICK Programming Software. Additional tools include a standalone Address Editor and Outline.  

## **Features**    
  
### ✨ Nickname Autocomplete    
- **Skip the addresses** – Select `Valve5` instead of typing `C123`    
- **Flexible search** – Prefix, partial match, or abbreviation (e.g., `Motor Speed` ↔ `Mtr_Spd`)    
- **Hover tooltips** – View address comments at a glance    
- **Exclusion filters** – Hide system or internal addresses (e.g., `SC/SD`, `__private__`)

![ClickNick autocomplete demo](https://github.com/user-attachments/assets/0275dcf4-6d79-4775-8763-18b13e8fd3a3)  
  
### 🛠️ Modern Address Editor    
- **Multi-window** – Edit different address sections simultaneously    
- **Bulk editing** – Edit before saving, copy/paste multiple cells, live duplicate detection and validation    
- **Search & Replace** (Ctrl+F / Ctrl+R) - With `Find in Selection` toggle   
- **Custom blocks** – Drag to create color-coded groups for organization and quick navigation

![Address Editor demo](https://github.com/user-attachments/assets/6fced9f5-2325-4867-ba23-d3b14ef8e866)  

> [!NOTE]  
> Nicknames edited in the Address Editor appear immediately in autocomplete. 
> Existing ladder logic refreshes after editing via the built-in Address Picker (Ctrl+T) or reopening the project.  

> [!IMPORTANT]      
> **Replace works on all visible editable columns.** Hidden columns (like Initial Value and Retentive) can be shown, 
> but watch out for numerical replacements—changing 1→2 (e.g., Alm1→Alm2) would also change 101 to 202. 
> Use **'Find in Selection'** to limit changes and avoid surprises.

### 📑 Outline Dock

![Outline dock screenshot](https://github.com/user-attachments/assets/352d9f6e-b9f2-43e7-b82e-81a92065c45a)

- **Navigate large projects** – See all your nicknames in an organized tree view  
- **Spot patterns** – Arrays and related items grouped automatically  
  - **Single underscores** create hierarchy. "SupplyTank_Pump_Status"
    ```
    SupplyTank
        └── Pump
            └── Status
    ```
  - **Trailing numbers** create arrays. "Alm1_id, Alm1_value, Alm2_id, Alm2_value" becomes:
    ```
    Alm[1-2]
    1
      ├── id
      └── value
    2
      ├── id
      └── value

    ```
- **One-click access** – Double-click to edit any address

### **Connectivity**  
- 🔌 Live ODBC database connection  
- 📄 CSV nickname import  

## **Why ClickNick?**    
✔ **Work faster** – Less time on manual address lookup  
✔ **Fewer mistakes** – Autocomplete reduces typos  
✔ **Stay organized** – Better tag management for complex projects 

> [!IMPORTANT]  
## Beta Disclaimer

ClickNick is beta software. Use at your own risk. The developers aren't liable for 
data loss, corruption, or process interruptions. Always back up your `.ckp` files.

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
| Compare (A with B) | 
| Timer, Counter | |
| Math | |
| Shift Register | |
| Copy | |
| Search | |
| Modbus Send/Receive | |

---

## **Documentation**  

- [Installation Guide](installation.md) – Python and uv setup  
- [Development](development.md) – Contributing workflows  
- [Publishing](publishing.md) – PyPI release instructions  

---

## **Motivation**

CLICK PLCs were my first controller, and I've built numerous projects with them. But as projects grew, remembering memory addresses instead of nicknames added overhead. Productivity and Do-More autocompleted nicknames as I type, why can't CLICK? **ClickNick was born**.

The built-in Address Picker was equally frustrating: either edit one at a time or export to Excel and re-import. Project templates required me to remember where I could add custom tags versus reserved areas. **The Address Editor solves this**—plus adds **Custom Blocks** to define distinct memory regions visually. See high-level project structure with the **Outline** dock.

I hope ClickNick helps new programmers choosing CLICK for its simplicity, as well as those maintaining legacy equipment—and serves as an example of how CLICK software can be extended.

---

*This project was built from
[simple-modern-uv](https://github.com/jlevy/simple-modern-uv).*

