# Light Material Design colors for block highlighting
# Maps friendly color names to hex codes
BLOCK_COLORS: dict[str, str] = {
    "Red": "#FFCDD2",
    "Pink": "#F8BBD9",
    "Purple": "#E1BEE7",
    "Deep Purple": "#D1C4E9",
    "Indigo": "#C5CAE9",
    "Blue": "#BBDEFB",
    "Light Blue": "#B3E5FC",
    "Cyan": "#B2EBF2",
    "Teal": "#B2DFDB",
    "Green": "#C8E6C9",
    "Light Green": "#DCEDC8",
    "Lime": "#F0F4C3",
    "Yellow": "#FFF9C4",
    "Amber": "#FFECB3",
    "Orange": "#FFE0B2",
    "Deep Orange": "#FFCCBC",
    "Brown": "#D7CCC8",
    "Blue Grey": "#CFD8DC",
}
# List of color names for iteration
BLOCK_COLOR_NAMES = list(BLOCK_COLORS.keys())


def get_block_color_hex(color_name: str) -> str | None:
    """Convert a block color name to its hex code.

    Args:
        color_name: Color name like "Red" or hex code like "#FFCDD2"

    Returns:
        Hex color code, or None if not found
    """
    # If it's already a hex code, return it
    if color_name.startswith("#"):
        return color_name
    # Look up by name (case-insensitive)
    for name, hex_code in BLOCK_COLORS.items():
        if name.lower() == color_name.lower():
            return hex_code
    return None
