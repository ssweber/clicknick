# ![ClickNick Logo](assets/clicknick_logo.png)

# clicknick

Context-aware nickname autocomplete for ClickPLC instruction windows.

![assets/clicknick_logo.png](https://github.com/user-attachments/assets/5a90fa58-6b2b-417d-9da9-74dac4c25095)

## Features

- **Smart Autocomplete**: Shows only relevant nicknames based on instruction type
- **Multiple Search Modes**: None, Prefix, Contains, and Fuzzy matching
- **Non-Intrusive**: Works alongside Click PLC without modifications

![ClickNick App](https://github.com/user-attachments/assets/29d8b222-8f22-44fb-bda9-311aaba8c60c)

## How to Run

(for now you'll need `uv` and `git` installed)
```
uvx --from git+https://github.com/ssweber/clicknick clicknick
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
