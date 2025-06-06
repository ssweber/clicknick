import re


class Nickname:
    """Represents a nickname with its address and metadata"""

    def __init__(
        self,
        nickname: str,
        address: str,
        initial_value: str,
        retentive: bool,
        comment: str = "",
        memory_type: str = "",
        used: bool = None,
        abbr_tags: str = "",
    ):
        self.nickname = nickname
        self.address = address
        self.initial_value = initial_value
        self.retentive = retentive
        self.comment = comment
        self._memory_type = memory_type
        self.used = used
        self.abbr_tags = abbr_tags

    @property
    def memory_type(self) -> str:
        """Get memory type from stored value or extract from address"""
        if not self._memory_type:
            pattern = re.compile(r"^([A-Z]+)")
            match = pattern.match(self.address)
            self._memory_type = match.group(1) if match else ""
        return self._memory_type

    @memory_type.setter
    def memory_type(self, value: str):
        """Set memory type"""
        self._memory_type = value

    @property
    def address_type(self) -> str:
        """Alias for memory_type for backward compatibility"""
        return self.memory_type

    def __repr__(self):
        return f"Nickname('{self.nickname}', '{self.address}')"

    def __str__(self):
        return self.nickname
