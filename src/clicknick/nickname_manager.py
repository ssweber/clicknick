import csv
import re
import os

from .window_mapping import DATA_TYPES


class NicknameManager:
    """Manages nicknames loaded from CSV with efficient filtering."""

    def __init__(self):
        self.nicknames = []  # List of dicts with 'Address' and 'Nickname' keys
        self._address_types_cache = None
        self._loaded_filepath = None
        self._last_load_timestamp = None

    @property
    def is_loaded(self) -> bool:
        """Check if nicknames data is loaded."""
        return len(self.nicknames) > 0

    def load_csv(self, filepath: str) -> bool:
        """
        Load nicknames from a CSV file and sort by Nickname.

        Args:
            filepath: Path to the CSV file

        Returns:
            bool: True if loading was successful
        """
        try:
            # Reset data
            self.nicknames = []
            self._address_types_cache = None

            # Load the CSV file
            with open(filepath, newline="") as csvfile:
                reader = csv.DictReader(csvfile)

                # Verify required columns exist
                required_columns = ["Address", "Nickname"]
                if not all(col in reader.fieldnames for col in required_columns):
                    print(f"CSV missing required columns: {required_columns}")
                    return False

                # Load all rows
                self.nicknames = list(reader)

            # Sort the list by Nickname
            self.nicknames.sort(key=lambda x: x["Nickname"])

            # Store filepath and timestamp for future checks
            self._loaded_filepath = filepath
            self._last_load_timestamp = os.path.getmtime(filepath)

            print(f"Loaded {len(self.nicknames)} nicknames from {filepath}")
            return True

        except Exception as e:
            print(f"Error loading CSV: {e}")
            return False

    def _check_for_file_updates(self) -> None:
        """Check if the loaded CSV file has been modified and reload if necessary."""
        if not self._loaded_filepath:
            return

        try:
            current_timestamp = os.path.getmtime(self._loaded_filepath)
            if current_timestamp != self._last_load_timestamp:
                print(f"Detected changes in {self._loaded_filepath}, reloading...")
                self.load_csv(self._loaded_filepath)
        except Exception as e:
            print(f"Error checking for file updates: {e}")

    def _extract_address_types(self) -> None:
        """Extract and cache address types from addresses."""
        if not self.is_loaded or self._address_types_cache is not None:
            return

        # Extract address type from each address (e.g., X, Y, C)
        self._address_types_cache = []
        pattern = re.compile(r"^([A-Z]+)")

        for item in self.nicknames:
            match = pattern.match(item["Address"])
            address_type = match.group(1) if match else ""
            self._address_types_cache.append(address_type)

    def get_nicknames_for_combobox(
        self, address_types: list[str], prefix: str = "", contains: bool = False
    ) -> list[str]:
        """
        Get filtered list of nicknames for the combobox.
        Performs a lazy check to reload data if the source file has changed.

        Args:
            address_types: List of allowed address types (X, Y, C, etc.)
            prefix: Optional text to filter nicknames
            contains: If True, match text anywhere in nickname; if False, match prefix only

        Returns:
            List of matching nicknames
        """
        # Lazy check for file updates
        self._check_for_file_updates()

        if not self.is_loaded or not address_types:
            return []

        # Extract address types if not already cached
        self._extract_address_types()

        result = []
        prefix = prefix.lower()

        # Filter by address type and text
        for i, item in enumerate(self.nicknames):
            # Check if address type matches
            if self._address_types_cache[i] not in address_types:
                continue

            nickname = item["Nickname"]
            nickname_lower = nickname.lower()

            # Apply text filter
            if not prefix:
                result.append(nickname)
            elif contains and prefix in nickname_lower:
                result.append(nickname)
            elif not contains and nickname_lower.startswith(prefix):
                result.append(nickname)

        return result

    def get_address_for_nickname(self, nickname: str) -> str | None:
        """
        Get the address for a given nickname.

        Args:
            nickname: The exact nickname to look up

        Returns:
            The corresponding address or None if not found
        """
        if not self.is_loaded:
            return None

        # Find exact match for the nickname
        for item in self.nicknames:
            if item["Nickname"] == nickname:
                return item["Address"]

        return None

    def is_valid_address_or_numeric(self, input_text):
        """
        Check if the input is a valid address or a numeric value.

        Args:
            input_text (str): The input to check

        Returns:
            bool: True if the input is a valid address or numeric value, False otherwise
        """
        # Check if the input is a valid address with correct prefix
        input_text = input_text.lower()

        for prefix in DATA_TYPES.keys():
            prefix = prefix.lower()
            if input_text.startswith(prefix) and input_text[len(prefix) :].isdigit():
                return True

        # Check if the input is just numbers or numbers with a decimal point
        if re.match(r"^[0-9]+(\.[0-9]+)?$", input_text):
            return True

        return False
