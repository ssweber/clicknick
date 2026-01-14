"""Service layer for business logic.

This package contains stateless services that coordinate operations on
AddressRow objects managed by SharedAddressData. Services separate business
logic from UI concerns and provide clear contracts for operations.

Services:
- ValidationService: Coordinate validation of AddressRow objects
- RowService: Multi-row operations (fill down, clone structure)
- BlockService: Block tag color computation and updates
- ImportService: CSV merge operations
- RowDependencyService: Sync interleaved pairs (T/TD, CT/CTD)

All services operate on the skeleton AddressRow objects in-place. Changes
should be made within a SharedAddressData.edit_session() context which
handles validation and notification automatically.
"""

from .block_service import BlockService
from .dependency_service import RowDependencyService
from .import_service import ImportService
from .row_service import RowService

__all__ = [
    "RowService",
    "BlockService",
    "ImportService",
    "RowDependencyService",
]
