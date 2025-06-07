import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Nickname:
    """Represents a nickname with its address and metadata"""
    
    nickname: str
    address: str
    data_type: str
    initial_value: str
    retentive: bool
    comment: str = ""
    memory_type: str = ""
    used: Optional[bool] = None
    abbr_tags: str = ""
    
    def __post_init__(self):
        """Store the original memory_type value for lazy evaluation"""
        self._memory_type = self.memory_type
    
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

    def details(self) -> str:
        """Generate a tooltip string for this nickname"""
        lines = [self.nickname]

        # Second line: data_type : Address
        if self.data_type:
            lines[0] += f" - {self.data_type} : {self.address}"
        else:
            lines[0] += f" - {self.address}"

        # Third line: Comment (if present)
        if self.comment:
            lines.append(f"'{self.comment}'")

        # Fourth line: Additional details (if any)
        details = []

        if self.used is False:
            details.append("Used: No")

        if self.initial_value and self.initial_value != "0":
            details.append(f"Initial Value: {self.initial_value}")

        if details:
            lines.append(", ".join(details))

        return "\n".join(lines)

    def __str__(self):
        return self.nickname