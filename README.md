![clicknick_logo](https://github.com/user-attachments/assets/2cb7f411-3174-478c-a6c9-409aaa788376)

# clicknick

Context-aware nickname autocomplete for ClickPLC instruction windows.

![CLICK_BJVV78ZqMR](https://github.com/user-attachments/assets/b17e364b-1cbe-4a15-ade5-d12fe652789e)


## Features

- **Smart Autocomplete**: Shows only relevant nicknames based on instruction type
- **Multiple Filter Modes**: Prefix, Contains, and Fuzzy matching
- **Exclude**: SC/SD addresses or your own
- **Non-Intrusive**: Works alongside Click PLC without modifications

![image](https://github.com/user-attachments/assets/d917cc7a-7ed2-4e99-a407-a730c1f4b8b0)


## How to Run

### Option 1: Using uv (recommended)
```
uvx clicknick
```
If you don't have uv installed, you can get it from: https://github.com/astral-sh/uv#installation

### Option 2: Using pip
```
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

