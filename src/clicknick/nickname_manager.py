import csv
import os
import re
from pathlib import Path

import pyodbc

from .filters import ContainsFilter, FuzzyFilter, NoneFilter, PrefixFilter


class NicknameManager:
    """Manages nicknames loaded from CSV with efficient filtering."""

    def _init_filters(self):
        """Initialize the search filter strategies"""
        self.filter_strategies = {
            "none": NoneFilter(),
            "prefix": PrefixFilter(),
            "contains": ContainsFilter(),
            "fuzzy": FuzzyFilter(),
        }

    def __init__(self):
        self.nicknames = []  # List of dicts with 'Address' and 'Nickname' keys
        self._address_types_cache = None
        self._loaded_filepath = None
        self._last_load_timestamp = None
        self._click_pid = None
        self._click_hwnd = None

        # Initialize filter strategies
        self._init_filters()

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
                hwnd_hex = format(click_hwnd, "08X")[-7:]

                # Build the expected database path
                username = os.environ.get("USERNAME")
                db_path = Path(f"C:/Users/{username}/AppData/Local/Temp/CLICK ({hwnd_hex})/SC_.mdb")

                if db_path.exists():
                    return str(db_path)

            # Fallback: search the temp directory for CLICK folders
            temp_dir = Path(os.environ.get("TEMP", ""))
            if temp_dir.exists():
                for folder in temp_dir.glob("CLICK (*)/"):
                    mdb_path = folder / "SC_.mdb"
                    if mdb_path.exists():
                        return str(mdb_path)

            return None

        except Exception as e:
            print(f"Error finding database: {e}")
            return None

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

            # Find available Access drivers
            available_drivers = [driver for driver in pyodbc.drivers() if "Access" in driver]

            if not available_drivers:
                print("No Microsoft Access drivers found on this system")
                return False

            # Try different drivers in order of preference
            access_driver = None
            driver_errors = []

            # Preferred driver order
            preferred_drivers = [
                "Microsoft Access Driver (*.mdb, *.accdb)",  # First try the most common one
                "Microsoft Access Driver (*.mdb)",  # Older driver that might be available
                "Microsoft Access Driver",  # Generic name that might work
            ]

            # Try drivers in order of preference, then try any other available Access drivers
            for driver in preferred_drivers + [
                d for d in available_drivers if d not in preferred_drivers
            ]:
                try:
                    conn_str = f"DRIVER={{{driver}}};DBQ={db_path};"
                    conn = pyodbc.connect(conn_str)
                    access_driver = driver
                    print(f"Successfully connected using driver: {driver}")
                    break
                except pyodbc.Error as e:
                    driver_errors.append(f"Driver '{driver}' failed: {str(e)}")
                    continue

            if not access_driver:
                error_msg = "Failed to connect with any Access driver:\n" + "\n".join(driver_errors)
                print(error_msg)
                return False

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
                self.nicknames.append(
                    {"Nickname": nickname, "Address": address, "MemoryType": memory_type}
                )

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

    def filter_results(
        self,
        nicknames: list[str],
        search_text: str,
        search_mode: str = "none",
        fuzzy_threshold: int = 60,
    ) -> list[str]:
        """
        Filter nicknames based on search text and mode.

        Args:
            nicknames: List of nicknames to filter
            search_text: Text to search for
            search_mode: Search strategy ("none", "prefix", "contains", "fuzzy")
            fuzzy_threshold: Threshold for fuzzy matching (0-100)

        Returns:
            Filtered list of nicknames
        """
        if not search_text or search_mode == "none":
            return nicknames

        strategy = self.filter_strategies.get(search_mode, self.filter_strategies["none"])

        # Update fuzzy threshold if using fuzzy search
        if search_mode == "fuzzy" and isinstance(strategy, FuzzyFilter):
            strategy.threshold = fuzzy_threshold

        return strategy.filter_matches(nicknames, search_text)

    def get_nicknames(
        self,
        address_types: list[str],
        prefix: str = "",
        contains: bool = False,
        exclude_sc_sd: bool = False,
        exclude_terms: str = "",
    ) -> list[str]:
        """
        Get filtered list of nicknames for the combobox.
        Performs a lazy check to reload data if the source file has changed.

        Args:
            address_types: List of allowed address types (X, Y, C, etc.)
            prefix: Optional text to filter nicknames
            contains: If True, match text anywhere in nickname; if False, match prefix only
            exclude_sc_sd: If True, exclude SC and SD addresses
            exclude_terms: Comma-separated list of terms to exclude

        Returns:
            List of matching nicknames
        """
        # Lazy check for file updates
        self._check_for_file_updates()

        if not self.is_loaded or not address_types:
            return []

        # Extract address types if not already cached
        self._extract_address_types()

        # Parse excluded terms
        excluded_terms = [term.strip().lower() for term in exclude_terms.split(",") if term.strip()]

        result = []
        prefix = prefix.lower()

        # Filter by address type and text
        for i, item in enumerate(self.nicknames):
            # Check if address type matches
            if self._address_types_cache[i] not in address_types:
                continue

            # Skip SC/SD addresses if requested
            address = item["Address"]
            if exclude_sc_sd and (address.startswith("SC") or address.startswith("SD")):
                continue

            nickname = item["Nickname"]
            nickname_lower = nickname.lower()

            # Skip if it contains any excluded terms
            if any(excluded_term in nickname_lower for excluded_term in excluded_terms):
                continue

            # Apply text filter
            if not prefix:
                result.append(nickname)
            elif contains and prefix in nickname_lower:
                result.append(nickname)
            elif not contains and nickname_lower.startswith(prefix):
                result.append(nickname)

        return result

    def get_nicknames_for_combobox(
        self,
        address_types: list[str],
        search_text: str = "",
        search_mode: str = "none",
        fuzzy_threshold: int = 60,
        exclude_sc_sd: bool = False,
        exclude_terms: str = "",
    ) -> list[str]:
        """
        Get filtered list of nicknames with search functionality.

        Args:
            address_types: List of allowed address types (X, Y, C, etc.)
            search_text: Text to search for in nicknames
            search_mode: Search strategy ("none", "prefix", "contains", "fuzzy")
            fuzzy_threshold: Threshold for fuzzy matching (0-100)
            exclude_sc_sd: If True, exclude SC and SD addresses
            exclude_terms: Comma-separated list of terms to exclude

        Returns:
            List of matching nicknames
        """
        # Get base nicknames filtered by address type and exclusions ONLY
        # Don't pass any text filtering to avoid double filtering
        base_nicknames = self.get_nicknames(
            address_types=address_types,
            exclude_sc_sd=exclude_sc_sd,
            exclude_terms=exclude_terms,
            # Note: NOT passing prefix or contains parameters
        )

        # Then apply search filtering
        return self.filter_results(
            nicknames=base_nicknames,
            search_text=search_text,
            search_mode=search_mode,
            fuzzy_threshold=fuzzy_threshold,
        )

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

    def get_available_access_drivers(self) -> list[str]:
        """
        Get list of available Microsoft Access ODBC drivers.

        Returns:
            List of available Access driver names
        """
        try:
            import pyodbc

            return [driver for driver in pyodbc.drivers() if "Access" in driver]
        except ImportError:
            return []
        except Exception as e:
            print(f"Error checking ODBC drivers: {e}")
            return []

    def has_access_driver(self) -> bool:
        """Check if any Microsoft Access ODBC driver is available."""
        return len(self.get_available_access_drivers()) > 0
