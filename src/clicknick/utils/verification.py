"""Verification utilities for MDB addresses and CDV files.

Provides comprehensive validation of PLC address data and DataView configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..models.address_row import get_addr_key, is_xd_yd_hidden_slot, parse_addr_key
from ..models.constants import ADDRESS_RANGES, NON_EDITABLE_TYPES, PAIRED_RETENTIVE_TYPES
from ..models.dataview_row import (
    MEMORY_TYPE_TO_CODE,
    TypeCode,
    get_type_code_for_address,
    is_address_writable,
    parse_address,
)
from ..models.validation import validate_initial_value, validate_nickname

if TYPE_CHECKING:
    from ..data.shared_data import SharedAddressData
    from ..models.address_row import AddressRow


@dataclass
class VerificationResult:
    """Results from verification process."""

    mdb_issues: list[str] = field(default_factory=list)
    cdv_issues: list[str] = field(default_factory=list)
    total_addresses: int = 0
    cdv_files_checked: int = 0

    @property
    def total_issues(self) -> int:
        """Total number of issues found."""
        return len(self.mdb_issues) + len(self.cdv_issues)

    @property
    def all_issues(self) -> list[str]:
        """All issues combined."""
        return self.mdb_issues + self.cdv_issues

    @property
    def passed(self) -> bool:
        """True if no issues found."""
        return self.total_issues == 0


def _check_retentive_pairs(all_rows: dict[int, AddressRow]) -> list[str]:
    """Check that T/TD and CT/CTD pairs have matching retentive settings.

    T and TD at the same address number should have the same retentive setting.
    Same for CT and CTD.

    Args:
        all_rows: Dict of addr_key -> AddressRow

    Returns:
        List of issue strings
    """
    issues: list[str] = []

    # PAIRED_RETENTIVE_TYPES = {"TD": "T", "CTD": "CT"}
    # We need to check TD->T and CTD->CT pairs

    for data_type, paired_type in PAIRED_RETENTIVE_TYPES.items():
        # Get address range for the data type
        addr_range = ADDRESS_RANGES.get(data_type)
        if not addr_range:
            continue

        min_addr, max_addr = addr_range
        for addr_num in range(min_addr, max_addr + 1):
            # Get the data row (TD or CTD)
            data_key = get_addr_key(data_type, addr_num)
            # Get the paired row (T or CT)
            paired_key = get_addr_key(paired_type, addr_num)

            data_row = all_rows.get(data_key)
            paired_row = all_rows.get(paired_key)

            if data_row and paired_row:
                if data_row.retentive != paired_row.retentive:
                    issues.append(
                        f"MDB: {paired_type}{addr_num} retentive={paired_row.retentive} "
                        f"but {data_type}{addr_num} retentive={data_row.retentive} (should match)"
                    )

    return issues


def verify_mdb_addresses(shared_data: SharedAddressData) -> list[str]:
    """Verify all MDB addresses for validity.

    Checks:
    - addr_key can be parsed back correctly
    - Address is within valid range for memory type
    - Nickname and initial value pass validation
    - NON_EDITABLE_TYPES have empty or "0" initial_value
    - XD/YD hidden slots don't have nicknames
    - T/TD and CT/CTD pairs have matching retentive settings

    Args:
        shared_data: The SharedAddressData containing all addresses

    Returns:
        List of issue strings (empty if all valid)
    """
    issues: list[str] = []
    all_rows = shared_data.all_rows

    # Build nickname dict for duplicate checking
    all_nicknames = {k: v.nickname for k, v in all_rows.items() if v.nickname}

    for addr_key, row in all_rows.items():
        display = f"{row.memory_type}{row.address}"

        # 1. Check addr_key can be parsed back correctly
        try:
            parsed_type, parsed_addr = parse_addr_key(addr_key)
            if parsed_type != row.memory_type or parsed_addr != row.address:
                issues.append(
                    f"MDB: AddrKey mismatch for {display} "
                    f"(key={addr_key}, parsed={parsed_type}{parsed_addr})"
                )
        except KeyError:
            issues.append(f"MDB: Invalid type index in addr_key {addr_key} for {display}")
            continue

        # 2. Check address is within valid range
        addr_range = ADDRESS_RANGES.get(row.memory_type)
        if addr_range:
            min_addr, max_addr = addr_range
            if not (min_addr <= row.address <= max_addr):
                issues.append(f"MDB: {display} out of range (valid: {min_addr}-{max_addr})")
        else:
            issues.append(f"MDB: Unknown memory type '{row.memory_type}' for address {row.address}")

        # 3. Validate nickname and initial value
        nick_valid, nick_error = validate_nickname(row.nickname, all_nicknames, addr_key)
        if not nick_valid:
            issues.append(f"MDB: {display} nickname invalid: {nick_error}")

        init_valid, init_error = validate_initial_value(row.initial_value, row.data_type)
        if not init_valid:
            issues.append(f"MDB: {display} initial value invalid: {init_error}")

        # 4. NON_EDITABLE_TYPES should have empty or "0" initial_value
        if row.memory_type in NON_EDITABLE_TYPES:
            if row.initial_value not in ("", "0"):
                issues.append(
                    f"MDB: {display} is NON_EDITABLE but has initial_value='{row.initial_value}'"
                )

        # 5. XD/YD hidden slots shouldn't have nicknames
        if is_xd_yd_hidden_slot(row.memory_type, row.address):
            if row.nickname:
                issues.append(
                    f"MDB: {display} is hidden XD/YD slot but has nickname='{row.nickname}'"
                )

    # 6. Check T/TD and CT/CTD retentive consistency
    issues.extend(_check_retentive_pairs(all_rows))

    return issues


def _validate_cdv_new_value(
    new_value: str,
    type_code: int,
    address: str,
    filename: str,
    row_num: int,
) -> list[str]:
    """Validate a CDV new_value against its type code.

    CDV stores values in specific formats:
    - BIT: "0" or "1"
    - INT: unsigned 32-bit (with sign extension for negatives)
    - INT2: unsigned 32-bit
    - HEX: decimal representation of hex value
    - FLOAT: IEEE 754 32-bit integer representation
    - TXT: ASCII code

    Args:
        new_value: The new value string from CDV
        type_code: The type code for this address
        address: The address string (for error messages)
        filename: The CDV filename (for error messages)
        row_num: The row number (for error messages)

    Returns:
        List of issue strings
    """
    issues: list[str] = []

    try:
        if type_code == TypeCode.BIT:
            if new_value not in ("0", "1"):
                issues.append(
                    f"CDV {filename} row {row_num}: {address} new_value '{new_value}' "
                    f"invalid for BIT (must be 0 or 1)"
                )

        elif type_code == TypeCode.INT:
            # Stored as unsigned 32-bit, should be valid integer
            val = int(new_value)
            # Check it's a reasonable unsigned 32-bit value
            if val < 0 or val > 0xFFFFFFFF:
                issues.append(
                    f"CDV {filename} row {row_num}: {address} new_value '{new_value}' "
                    f"out of range for INT storage"
                )

        elif type_code == TypeCode.INT2:
            val = int(new_value)
            if val < 0 or val > 0xFFFFFFFF:
                issues.append(
                    f"CDV {filename} row {row_num}: {address} new_value '{new_value}' "
                    f"out of range for INT2 storage"
                )

        elif type_code == TypeCode.HEX:
            val = int(new_value)
            if val < 0 or val > 0xFFFF:
                issues.append(
                    f"CDV {filename} row {row_num}: {address} new_value '{new_value}' "
                    f"out of range for HEX (0-65535)"
                )

        elif type_code == TypeCode.FLOAT:
            # Should be valid integer (IEEE 754 representation)
            val = int(new_value)
            if val < 0 or val > 0xFFFFFFFF:
                issues.append(
                    f"CDV {filename} row {row_num}: {address} new_value '{new_value}' "
                    f"invalid for FLOAT storage"
                )

        elif type_code == TypeCode.TXT:
            val = int(new_value)
            if val < 0 or val > 127:
                issues.append(
                    f"CDV {filename} row {row_num}: {address} new_value '{new_value}' "
                    f"out of range for TXT (0-127 ASCII)"
                )

    except ValueError:
        issues.append(
            f"CDV {filename} row {row_num}: {address} new_value '{new_value}' is not a valid number"
        )

    return issues


def _verify_single_cdv(cdv_path: Path) -> list[str]:
    """Verify a single CDV file.

    Args:
        cdv_path: Path to the CDV file

    Returns:
        List of issue strings
    """
    from ..views.dataview_editor.cdv_file import load_cdv

    issues: list[str] = []
    filename = cdv_path.name

    try:
        rows, has_new_values = load_cdv(cdv_path)
    except Exception as e:
        issues.append(f"CDV {filename}: Error loading file - {e}")
        return issues

    for i, row in enumerate(rows):
        if row.is_empty:
            continue

        row_num = i + 1

        # 1. Check address format is valid
        parsed = parse_address(row.address)
        if not parsed:
            issues.append(f"CDV {filename} row {row_num}: Invalid address format '{row.address}'")
            continue

        mem_type, num_part = parsed

        # 2. Check memory type is known
        if mem_type not in MEMORY_TYPE_TO_CODE:
            issues.append(f"CDV {filename} row {row_num}: Unknown memory type '{mem_type}'")
            continue

        # 3. Check address number is within range
        addr_range = ADDRESS_RANGES.get(mem_type)
        if addr_range:
            try:
                # Handle 'u' suffix for XD/YD upper bytes
                addr_num = int(num_part.rstrip("uU"))
                min_addr, max_addr = addr_range
                if not (min_addr <= addr_num <= max_addr):
                    issues.append(
                        f"CDV {filename} row {row_num}: {row.address} out of range "
                        f"(valid: {min_addr}-{max_addr})"
                    )
            except ValueError:
                issues.append(f"CDV {filename} row {row_num}: Invalid address number '{num_part}'")

        # 4. Check type code matches expected
        expected_code = get_type_code_for_address(row.address)
        if expected_code is not None and row.type_code != expected_code:
            issues.append(
                f"CDV {filename} row {row_num}: Type code mismatch for {row.address} "
                f"(has {row.type_code}, expected {expected_code})"
            )

        # 5. If new_value is set, validate format
        if row.new_value:
            new_value_issues = _validate_cdv_new_value(
                row.new_value, row.type_code, row.address, filename, row_num
            )
            issues.extend(new_value_issues)

            # 6. If new_value is set, address must be writable
            if not is_address_writable(row.address):
                issues.append(
                    f"CDV {filename} row {row_num}: {row.address} has new_value "
                    f"but address is not writable"
                )

    return issues


def verify_cdv_files(project_path: Path | str) -> tuple[list[str], int]:
    """Verify all CDV files in a project's DataView folder.

    Checks:
    - Address format is valid
    - Memory type is known
    - Address number is within valid range
    - Type code matches expected for address type
    - If new_value is set, validate format against type
    - If new_value is set, address must be writable

    Args:
        project_path: Path to the CLICK project folder

    Returns:
        Tuple of (issues list, files checked count)
    """
    from ..views.dataview_editor.cdv_file import (
        get_dataview_folder,
        list_cdv_files,
    )

    issues: list[str] = []
    files_checked = 0

    try:
        dataview_folder = get_dataview_folder(project_path)
        if not dataview_folder:
            return issues, files_checked

        cdv_files = list_cdv_files(dataview_folder)
        for cdv_path in cdv_files:
            files_checked += 1
            file_issues = _verify_single_cdv(cdv_path)
            issues.extend(file_issues)

    except Exception as e:
        issues.append(f"CDV: Error accessing dataview folder - {e}")

    return issues, files_checked


def run_verification(
    shared_data: SharedAddressData,
    project_path: Path | str,
) -> VerificationResult:
    """Run full verification of MDB addresses and CDV files.

    Args:
        shared_data: The SharedAddressData containing all addresses
        project_path: Path to the CLICK project folder

    Returns:
        VerificationResult with all findings
    """
    result = VerificationResult()
    result.total_addresses = len(shared_data.all_rows)

    # Verify MDB addresses
    result.mdb_issues = verify_mdb_addresses(shared_data)

    # Verify CDV files
    result.cdv_issues, result.cdv_files_checked = verify_cdv_files(project_path)

    return result
