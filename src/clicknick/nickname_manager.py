import csv
import os

from .address_editor.address_model import strip_header_tag
from .filters import ContainsFilter, ContainsPlusFilter, NoneFilter, PrefixFilter
from .mdb_shared import (
    create_access_connection,
    find_click_database,
    get_available_access_drivers,
)
from .nickname import Nickname


class NicknameManager:
    """Manages nicknames loaded from CSV or database with efficient filtering."""

    def __init__(self, settings=None, filter_strategies=None):
        self.nicknames: list[Nickname] = []  # List of Nickname objects
        self._loaded_filepath = None
        self._last_load_timestamp = None
        self._click_pid = None
        self._click_hwnd = None
        self.settings = settings  # Store reference to app settings

        # Use provided filter strategies or create default ones
        if filter_strategies:
            self.filter_strategies = filter_strategies
        else:
            self.filter_strategies = {
                "none": NoneFilter(),
                "prefix": PrefixFilter(),
                "contains": ContainsFilter(),
                "containsplus": ContainsPlusFilter(),
            }

    @property
    def is_loaded(self) -> bool:
        """Check if nicknames data is loaded."""
        return len(self.nicknames) > 0

    def apply_sorting(self, sort_by_nickname: bool = False):
        """
        Apply sorting to the loaded nicknames.

        Args:
            sort_by_nickname: If True, sort by nickname alphabetically.
                             If False, keep original order (memory type + address).
        """
        if not self.is_loaded:
            return

        if sort_by_nickname:
            self.nicknames.sort(key=lambda x: x.nickname)
        # If False, keep the original database/CSV order (MemoryType + Address)

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
        for nickname_obj in self.nicknames:
            if nickname_obj.nickname == nickname:
                return nickname_obj.address

        return None

    def get_nickname_details(self, nickname: str) -> str:
        """
        Get detailed information for a given nickname.

        Args:
            nickname: The exact nickname to look up

        Returns:
            Detailed string with address, data type, initial value, and comment
        """
        if not self.is_loaded:
            return ""

        # Find exact match for the nickname
        for nickname_obj in self.nicknames:
            if nickname_obj.nickname == nickname:
                return nickname_obj.details()

        return ""

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

                # Reapply sorting preference after reload
                if self.settings:
                    self.apply_sorting(self.settings.sort_by_nickname)
        except Exception as e:
            print(f"Error checking for file updates: {e}")

    def get_filtered_nicknames(self, address_types: list[str], search_text: str = "") -> list[str]:
        """
        Get filtered list of nickname strings using current app settings.

        Args:
            address_types: List of allowed address types (X, Y, C, etc.)
            search_text: Text to search for in nicknames

        Returns:
            List of matching nickname strings
        """
        # Lazy check for file updates
        self._check_for_file_updates()

        if not self.is_loaded or not address_types:
            return []

        # Get filtering parameters from settings (with fallbacks)
        if self.settings:
            search_mode = self.settings.search_mode
            exclude_sc_sd = self.settings.exclude_sc_sd
            excluded_terms = self.settings.get_exclude_terms_list()
        else:
            # Fallback values if no settings available
            search_mode = "none"
            exclude_sc_sd = False
            excluded_terms = []

        # Filter by address type and exclusions
        filtered_objects = []
        for nickname_obj in self.nicknames:
            # Check if address type matches
            if nickname_obj.address_type not in address_types:
                continue

            # Skip SC/SD addresses if requested
            if exclude_sc_sd and (
                nickname_obj.address.startswith("SC") or nickname_obj.address.startswith("SD")
            ):
                continue

            # Skip if it contains any excluded terms
            nickname_lower = nickname_obj.nickname.lower()
            if any(excluded_term in nickname_lower for excluded_term in excluded_terms):
                continue

            filtered_objects.append(nickname_obj)

        # Apply search filtering if search text provided
        if not search_text or search_mode == "none":
            return [obj.nickname for obj in filtered_objects]

        strategy = self.filter_strategies.get(search_mode, self.filter_strategies["none"])
        search_filtered_objects = strategy.filter_matches(filtered_objects, search_text)

        return [obj.nickname for obj in search_filtered_objects]

    def _generate_abbreviation_tags(self):
        """Generate abbreviation tags for containsplus filtering"""
        if not self.is_loaded:
            return

        containsplus_filter = self.filter_strategies.get("containsplus")
        if not containsplus_filter:
            return

        for nickname_obj in self.nicknames:
            nickname_obj.abbr_tags = containsplus_filter.generate_tags(nickname_obj.nickname)

    def load_csv(self, filepath: str) -> bool:
        """
        Load nicknames from a CSV file in original order (MemoryType + Address).

        Args:
            filepath: Path to the CSV file

        Returns:
            bool: True if loading was successful
        """
        try:
            # Reset data
            self.nicknames = []
            self._click_pid = None
            self._click_hwnd = None

            # Load the CSV file
            with open(filepath, newline="") as csvfile:
                reader = csv.DictReader(csvfile)
                # Verify required columns exist
                required_columns = [
                    "Address",
                    "Nickname",
                    "Data Type",
                    "Initial Value",
                    "Retentive",
                    "Address Comment",
                ]
                if not all(col in reader.fieldnames for col in required_columns):
                    print(f"CSV missing required columns: {required_columns}")
                    return False

                # Convert to Nickname objects
                for row in reader:
                    nickname_obj = Nickname(
                        nickname=row["Nickname"],
                        address=row["Address"],
                        data_type=row["Data Type"],
                        initial_value=row["Initial Value"],
                        retentive=row["Retentive"] == "Yes",
                        comment=strip_header_tag(row["Address Comment"]),
                        address_type="".join(c for c in row["Address"] if c.isupper()),
                    )
                    self.nicknames.append(nickname_obj)

            # Generate abbreviation tags
            self._generate_abbreviation_tags()

            # Store filepath and timestamp for future checks
            self._loaded_filepath = filepath
            self._last_load_timestamp = os.path.getmtime(filepath)

            print(f"Loaded {len(self.nicknames)} nicknames from {filepath}")
            return True

        except Exception as e:
            print(f"Error loading CSV: {e}")
            return False

    def has_access_driver(self) -> bool:
        """Check if any Microsoft Access ODBC driver is available."""
        return len(get_available_access_drivers()) > 0

    def _convert_database_data_type(self, text: str) -> str:
        type_mapping = {0: "BIT", 1: "INT", 2: "INT2", 3: "FLOAT", 4: "HEX", 6: "TEXT"}
        return type_mapping.get(text, "")

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
            db_path = find_click_database(click_pid, click_hwnd)
            if not db_path:
                print("Could not locate CLICK database file")
                return False

            # Connect to the database
            try:
                conn = create_access_connection(db_path)
            except RuntimeError as e:
                print(str(e))
                return False

            cursor = conn.cursor()

            # Execute query to get all nicknames
            query = """
                SELECT Nickname, MemoryType & Address AS AddressInfo, MemoryType, DataType, Use as Used, InitialValue, Retentive, Comment
                FROM address 
                WHERE Nickname <> ''
                ORDER BY MemoryType, Address;
            """
            cursor.execute(query)

            # Process results into Nickname objects
            self.nicknames = []
            for row in cursor.fetchall():
                (
                    nickname,
                    address,
                    memory_type,
                    data_type,
                    used,
                    initial_value,
                    retentive,
                    comment,
                ) = row
                nickname_obj = Nickname(
                    nickname=nickname,
                    address=address,
                    data_type=self._convert_database_data_type(data_type),
                    initial_value=initial_value,
                    retentive=retentive,
                    comment=strip_header_tag(comment),
                    address_type=memory_type,
                    used=used,
                )
                self.nicknames.append(nickname_obj)

            # Close connection
            cursor.close()
            conn.close()

            # Generate abbreviation tags
            self._generate_abbreviation_tags()

            # Store filepath and timestamp for future checks
            self._loaded_filepath = db_path
            self._last_load_timestamp = os.path.getmtime(db_path)

            print(f"Loaded {len(self.nicknames)} nicknames from database at {db_path}")
            return True

        except Exception as e:
            print(f"Error loading from database: {e}")
            return False
