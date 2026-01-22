"""Service layer for business logic.

This package contains services that coordinate operations on AddressRow
objects managed by SharedAddressData. Services separate business logic
from UI concerns and provide clear contracts for operations.

Services:
- NicknameIndexService: O(1) nickname lookups and duplicate detection (stateful)
- RowService: Multi-row operations (fill down, clone structure)
- BlockService: Block tag color computation and updates
- ImportService: CSV merge operations
- RowDependencyService: Sync interleaved pairs (T/TD, CT/CTD)

All services operate on the skeleton AddressRow objects in-place. Changes
should be made within a SharedAddressData.edit_session() context which
handles validation and notification automatically.
"""

from .block_service import BlockService

# from .dependency_service import RowDependencyService
from .import_service import ImportService
from .nickname_index_service import NicknameIndexService
from .row_service import RowService

__all__ = [
    "NicknameIndexService",
    "RowService",
    "BlockService",
    "ImportService",
    "RowDependencyService",
]
