from dataclasses import dataclass


@dataclass
class Nickname:
    """Represents a nickname with its address and metadata"""

    nickname: str
    address: str
    data_type: str
    initial_value: str
    retentive: bool
    comment: str = ""
    address_type: str = ""
    used: bool | None = None
    abbr_tags: str = ""

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

    def __eq__(self, other):
        """Two nicknames are equal if they have the same nickname and address"""
        if not isinstance(other, Nickname):
            return False
        return self.nickname == other.nickname and self.address == other.address

    def __hash__(self):
        """Make the object hashable based on nickname and address"""
        return hash((self.nickname, self.address))

    def __str__(self):
        return self.nickname
