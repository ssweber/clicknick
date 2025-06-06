import re


class Nickname:
    """Represents a nickname with its address and metadata"""

    def __init__(
        self,
        nickname: str,
        address: str,
        data_type: str,
        initial_value: str,
        retentive: bool,
        comment: str = "",
        memory_type: str = "",
        used: bool = None,
        abbr_tags: str = "",
    ):
        self.nickname = nickname
        self.address = address
        self.data_type = data_type
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
        # First line: data_type : Address
        if self.data_type:
            first_line = f"{self.data_type} : {self.address}"
        else:
            first_line = self.address

        # Second line: Comment (if any)
        lines = [first_line]
        if self.comment:
            lines.append(self.comment)

        # Third line: Additional details (if any)
        third_line_parts = []

        # Add "Used: No" only if used is False
        if self.used is False:
            third_line_parts.append("Used: No")

        # Add initial value if it's not '0' or empty
        if self.initial_value and self.initial_value != "0":
            third_line_parts.append(f"Initial Value: {self.initial_value}")

        # Add third line if there are any details
        if third_line_parts:
            lines.append(", ".join(third_line_parts))

        return "\n".join(lines)

    def __str__(self):
        return self.nickname
