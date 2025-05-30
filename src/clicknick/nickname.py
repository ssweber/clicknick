import re


class Nickname:
    """Represents a nickname with its address and metadata"""

    def __init__(self, nickname: str, address: str, memory_type: str = "", abbr_tags: str = ""):
        self.nickname = nickname
        self.address = address
        self.memory_type = memory_type
        self.abbr_tags = abbr_tags
        self._address_type = None

    @property
    def address_type(self) -> str:
        """Extract address type (e.g., X, Y, C) from address"""
        if self._address_type is None:
            pattern = re.compile(r"^([A-Z]+)")
            match = pattern.match(self.address)
            self._address_type = match.group(1) if match else ""
        return self._address_type

    def __repr__(self):
        return f"Nickname('{self.nickname}', '{self.address}')"

    def __str__(self):
        return self.nickname
