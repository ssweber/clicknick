"""Verification utilities for MDB addresses and CDV files.

Provides comprehensive validation of PLC address data and DataView configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pyclickplc.addresses import get_addr_key, is_xd_yd_hidden_slot, parse_addr_key
from pyclickplc.banks import BANKS, NON_EDITABLE_TYPES, PAIRED_RETENTIVE_TYPES

from ..models.validation import validate_initial_value, validate_nickname
from ..views.dataview_editor.cdv_file import check_cdv_files

if TYPE_CHECKING:
    from ..data.shared_data import SharedAddressData
    from ..models.address_row import AddressRow


# Memory types where underscore-prefixed nicknames are expected (system-defined)
SYSTEM_NICKNAME_TYPES: frozenset[str] = frozenset({"SC", "SD", "X"})


@dataclass
class VerificationResult:
    """Results from verification process."""

    mdb_issues: list[str] = field(default_factory=list)
    cdv_issues: list[str] = field(default_factory=list)
    # Separate list for system nickname issues (underscore prefix in SC/SD/X)
    system_nickname_issues: list[str] = field(default_factory=list)
    total_addresses: int = 0
    cdv_files_checked: int = 0

    @property
    def total_issues(self) -> int:
        """Total number of actionable issues (excludes system nickname issues)."""
        return len(self.mdb_issues) + len(self.cdv_issues)

    @property
    def all_issues(self) -> list[str]:
        """All actionable issues combined."""
        return self.mdb_issues + self.cdv_issues

    @property
    def passed(self) -> bool:
        """True if no actionable issues found."""
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
        bank = BANKS.get(data_type)
        if not bank:
            continue

        min_addr, max_addr = bank.min_addr, bank.max_addr
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


def verify_mdb_addresses(shared_data: SharedAddressData) -> tuple[list[str], list[str]]:
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
        Tuple of (issues, system_nickname_issues) where system_nickname_issues
        contains "Cannot start with _" errors for SC/SD/X types.
    """
    issues: list[str] = []
    system_nickname_issues: list[str] = []
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
        bank = BANKS.get(row.memory_type)
        if bank:
            min_addr, max_addr = bank.min_addr, bank.max_addr
            if not (min_addr <= row.address <= max_addr):
                issues.append(f"MDB: {display} out of range (valid: {min_addr}-{max_addr})")
        else:
            issues.append(f"MDB: Unknown memory type '{row.memory_type}' for address {row.address}")

        # 3. Validate nickname and initial value
        nick_valid, nick_error = validate_nickname(row.nickname, all_nicknames, addr_key)
        if not nick_valid:
            # Separate out "Cannot start with _" for system types (SC/SD/X)
            if nick_error == "Cannot start with _" and row.memory_type in SYSTEM_NICKNAME_TYPES:
                system_nickname_issues.append(
                    f"MDB: {display} nickname '{row.nickname}' starts with underscore"
                )
            else:
                issues.append(f"MDB: {display} nickname invalid: {nick_error}")

        init_valid, init_error = validate_initial_value(row.initial_value, row.data_type)
        if not init_valid:
            issues.append(f"MDB: {display} initial value invalid: {init_error}")

        # 4. NON_EDITABLE_TYPES should have empty or "0" initial_value
        if row.memory_type in NON_EDITABLE_TYPES:
            if row.initial_value not in ("", "0"):
                nick_part = f" nickname '{row.nickname}'" if row.nickname else ""
                issues.append(
                    f"MDB: {display}{nick_part} is NON_EDITABLE but has "
                    f"initial_value='{row.initial_value}'"
                )

        # 5. XD/YD hidden slots shouldn't have nicknames
        if is_xd_yd_hidden_slot(row.memory_type, row.address):
            if row.nickname:
                issues.append(
                    f"MDB: {display} is hidden XD/YD slot but has nickname='{row.nickname}'"
                )

    # 6. Check T/TD and CT/CTD retentive consistency
    issues.extend(_check_retentive_pairs(all_rows))

    return issues, system_nickname_issues


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
    return check_cdv_files(project_path)


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
    result.mdb_issues, result.system_nickname_issues = verify_mdb_addresses(shared_data)

    # Verify CDV files
    result.cdv_issues, result.cdv_files_checked = verify_cdv_files(project_path)

    return result
