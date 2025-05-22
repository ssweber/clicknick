import csv
import re
import os
from pathlib import Path

import pyodbc

from .window_mapping import DATA_TYPES


class NicknameManager:
    """Manages nicknames loaded from CSV with efficient filtering."""

    def __init__(self):
        self.nicknames = []  # List of dicts with 'Address' and 'Nickname' keys
        self._address_types_cache = None
        self._loaded_filepath = None
        self._last_load_timestamp = None
        self._click_pid = None
        self._click_hwnd = None

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
            self._click_pid = None
            self._click_hwnd = None

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
        """Check if the loaded file has been modified and reload if necessary."""
        if not self._loaded_filepath:
            return

        try:
            current_timestamp = os.path.getmtime(self._loaded_filepath)
            if current_timestamp != self._last_load_timestamp:
                print(f"Detected changes in {self._loaded_filepath}, reloading...")
                
                # If we loaded from database, reload using the stored PID and handle
                if self._click_pid and self._click_hwnd:
                    self.load_from_database(self._click_pid, self._click_hwnd)
                else:
                    # Otherwise reload from CSV
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
            
    def load_from_database(self, click_pid=None, click_hwnd=None):
        """
        Load nicknames directly from the CLICK Programming Software's Access database.
        
        Args:
            click_pid: Process ID of the CLICK software
            click_hwnd: Window handle of the CLICK software
            
        Returns:
            bool: True if loading was successful
        """
        try:
            # Save the Click PID and window handle for future reloads
            self._click_pid = click_pid
            self._click_hwnd = click_hwnd
            
            # Find the database path
            db_path = self._find_click_database(click_pid, click_hwnd)
            if not db_path:
                print("Could not locate CLICK database file")
                return False
                
            # Connect to the database
            conn_str = f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};"
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()
            
            # Execute query to get all nicknames
            query = """
                SELECT Nickname, MemoryType & Address AS AddressInfo, MemoryType 
                FROM address 
                WHERE Nickname <> ''
                ORDER BY MemoryType, Address;
            """
            cursor.execute(query)
            
            # Process results
            self.nicknames = []
            for row in cursor.fetchall():
                nickname, address, memory_type = row
                self.nicknames.append({
                    'Nickname': nickname,
                    'Address': address,
                    'MemoryType': memory_type
                })
                
            # Close connection
            cursor.close()
            conn.close()
            
            # Store filepath and timestamp for future checks
            self._loaded_filepath = db_path
            self._last_load_timestamp = os.path.getmtime(db_path)
            
            # Reset address type cache
            self._address_types_cache = None
            
            print(f"Loaded {len(self.nicknames)} nicknames from database at {db_path}")
            return True
            
        except Exception as e:
            print(f"Error loading from database: {e}")
            return False
    
    def _find_click_database(self, click_pid=None, click_hwnd=None):
        """
        Find the CLICK Programming Software's Access database file.
        
        Args:
            click_pid: Process ID of the CLICK software
            click_hwnd: Window handle of the CLICK software
            
        Returns:
            str: Path to the database file or None if not found
        """
        try:
            # If we have window handle in hex format, convert it to a proper format
            # similar to what the AutoHotkey script does
            if click_hwnd:
                # Convert window handle to uppercase hex string without '0x' prefix
                hwnd_hex = format(click_hwnd, '08X')[-7:]
                
                # Build the expected database path
                username = os.environ.get('USERNAME')
                db_path = Path(f"C:/Users/{username}/AppData/Local/Temp/CLICK ({hwnd_hex})/SC_.mdb")
                
                if db_path.exists():
                    return str(db_path)
            
            # Fallback: search the temp directory for CLICK folders
            temp_dir = Path(os.environ.get('TEMP', ''))
            if temp_dir.exists():
                for folder in temp_dir.glob("CLICK (*)/"):
                    mdb_path = folder / "SC_.mdb"
                    if mdb_path.exists():
                        return str(mdb_path)
            
            return None
            
        except Exception as e:
            print(f"Error finding database: {e}")
            return None

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