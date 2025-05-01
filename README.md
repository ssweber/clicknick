# ![ClickNick Logo](assets/clicknick_logo.png)

# clicknick

Context-aware nickname autocomplete for ClickPLC instruction windows.

![assets/clicknick_logo.png](https://github.com/user-attachments/assets/5a90fa58-6b2b-417d-9da9-74dac4c25095)

## Features

- **Smart Autocomplete**: Shows only relevant nicknames based on instruction type
- **Multiple Filter Modes**: Prefix, Contains, and Fuzzy matching
- **Non-Intrusive**: Works alongside Click PLC without modifications

![ClickNick App](https://github.com/user-attachments/assets/29d8b222-8f22-44fb-bda9-311aaba8c60c)

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

- Get feedback and publish to PyPI
- Add support for inserting Nickname/Address into Math equation

* * *

## Project Docs

For how to install uv and Python, see [installation.md](installation.md).

For development workflows, see [development.md](development.md).

For instructions on publishing to PyPI, see [publishing.md](publishing.md).

* * *

*This project was built from
[simple-modern-uv](https://github.com/jlevy/simple-modern-uv).*

