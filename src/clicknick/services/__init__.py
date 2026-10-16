"""Service layer for business logic.

This package contains services that coordinate operations on AddressRow
objects managed by AddressStore. Services separate business logic
from UI concerns and provide clear contracts for operations.

Services:
- NicknameIndexService: O(1) nickname lookups and duplicate detection (stateful)
- RowService: Multi-row operations (fill down, clone structure)
- BlockService: Block tag color computation and updates
- ImportService: CSV merge operations

AddressRow objects are immutable. Services write changes through the
EditSession yielded by AddressStore.edit_session(), which applies cascades,
validation and notification when it exits.
"""

from .annotation_service import AnnotationService
from .block_service import BlockService
from .import_service import ImportService
from .nickname_index_service import NicknameIndexService
from .row_service import RowService

__all__ = [
    "AnnotationService",
    "NicknameIndexService",
    "RowService",
    "BlockService",
    "ImportService",
]
