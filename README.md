![clicknick_logo](https://github.com/user-attachments/assets/2cb7f411-3174-478c-a6c9-409aaa788376)

# clicknick

Context-aware nickname autocomplete for ClickPLC instruction windows.

![CLICK_BJVV78ZqMR](https://github.com/user-attachments/assets/b17e364b-1cbe-4a15-ade5-d12fe652789e)


## Features

- **Smart Autocomplete**: Shows only relevant nicknames based on instruction type
- **Multiple Filter Modes**: Prefix, Contains, and Contains + Abbreviation matching
- **Exclude**: SC/SD addresses or your own
- **Non-Intrusive**: Works alongside Click PLC without modifications

![image](https://github.com/user-attachments/assets/ee627c86-801c-49ab-acff-85b906c34b06)

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

1. Select your ClickPLC nickname CSV file
2. Connect to your Click PLC instance
3. Start monitoring
4. Open ClickPLC Instruction window and Type in added Combobox-Input to see autocomplete suggestions

## Supported Windows

- Contact Normally Open/Closed
- Edge Contact
- Out, Set, Reset
- Compare (A with B)
- Timer, Counter
- Math instructions
- Shift Register
- Copy instruction
- Search instruction
- Search & Replace dialog

## Requirements

- Windows 10/11
- Click PLC Software

## Roadmap

- Add support for inserting Nickname/Address into Math equation

* * *

## Project Docs

For how to install uv and Python, see [installation.md](installation.md).

For development workflows, see [development.md](development.md).

For instructions on publishing to PyPI, see [publishing.md](publishing.md).

* * *

*This project was built from
[simple-modern-uv](https://github.com/jlevy/simple-modern-uv).*

