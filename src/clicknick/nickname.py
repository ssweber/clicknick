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
        # First line: Address/Data_Type - Comment
        first_line_parts = []
        
        # Add address and data type
        if self.data_type:
            first_line_parts.append(f"{self.address}/{self.data_type}")
        else:
            first_line_parts.append(self.address)
        
        # Add comment if available
        if self.comment:
            first_line_parts.append(f"- {self.comment}")
        
        first_line = " ".join(first_line_parts)
        
        # Second line: Additional details (if any)
        second_line_parts = []
        
        # Add "Used: No" only if used is False
        if self.used is False:
            second_line_parts.append("Used: No")
        
        # Add initial value if it's not '0' or empty
        if self.initial_value and self.initial_value != '0':
            second_line_parts.append(f"Initial Value: {self.initial_value}")
        
        # Combine lines
        if second_line_parts:
            return first_line + "\n" + ", ".join(second_line_parts)
        else:
            return first_line

    def __str__(self):
        return self.nickname
