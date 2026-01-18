"""Unit tests for NicknameIndexService."""

from clicknick.models.address_row import AddressRow
from clicknick.services.nickname_index_service import NicknameIndexService


class TestNicknameIndexServiceBasic:
    """Basic tests for NicknameIndexService."""

    def test_empty_service(self):
        """New service has empty indices."""
        service = NicknameIndexService()
        assert service.get_addr_keys("anything") == set()
        assert service.get_addr_keys_insensitive("anything") == set()
        assert service.is_duplicate("anything", 0) is False

    def test_rebuild_index_single_row(self):
        """Rebuild with single row indexes nickname."""
        service = NicknameIndexService()
        rows = [
            AddressRow(memory_type="X", address=1, nickname="Motor1"),
        ]
        service.rebuild_index(rows)

        assert service.get_addr_keys("Motor1") == {rows[0].addr_key}
        assert service.get_addr_keys_insensitive("motor1") == {rows[0].addr_key}

    def test_rebuild_index_multiple_rows(self):
        """Rebuild with multiple rows indexes all nicknames."""
        service = NicknameIndexService()
        rows = [
            AddressRow(memory_type="X", address=1, nickname="Motor1"),
            AddressRow(memory_type="X", address=2, nickname="Motor2"),
            AddressRow(memory_type="Y", address=1, nickname="Valve1"),
        ]
        service.rebuild_index(rows)

        assert service.get_addr_keys("Motor1") == {rows[0].addr_key}
        assert service.get_addr_keys("Motor2") == {rows[1].addr_key}
        assert service.get_addr_keys("Valve1") == {rows[2].addr_key}

    def test_rebuild_index_skips_empty_nicknames(self):
        """Rebuild skips rows with empty nicknames."""
        service = NicknameIndexService()
        rows = [
            AddressRow(memory_type="X", address=1, nickname="Motor1"),
            AddressRow(memory_type="X", address=2, nickname=""),  # Empty
            AddressRow(memory_type="X", address=3, nickname="Motor3"),
        ]
        service.rebuild_index(rows)

        assert service.get_addr_keys("Motor1") == {rows[0].addr_key}
        assert service.get_addr_keys("") == set()
        assert service.get_addr_keys("Motor3") == {rows[2].addr_key}

    def test_rebuild_index_clears_previous(self):
        """Rebuild clears previous index data."""
        service = NicknameIndexService()

        # First build
        rows1 = [AddressRow(memory_type="X", address=1, nickname="OldName")]
        service.rebuild_index(rows1)
        assert service.get_addr_keys("OldName") == {rows1[0].addr_key}

        # Rebuild with different data
        rows2 = [AddressRow(memory_type="X", address=2, nickname="NewName")]
        service.rebuild_index(rows2)

        assert service.get_addr_keys("OldName") == set()  # Cleared
        assert service.get_addr_keys("NewName") == {rows2[0].addr_key}


class TestNicknameIndexServiceCaseSensitivity:
    """Tests for case-sensitive vs case-insensitive lookups."""

    def test_get_addr_keys_exact_case(self):
        """get_addr_keys requires exact case match."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        assert service.get_addr_keys("Motor1") == {rows[0].addr_key}
        assert service.get_addr_keys("motor1") == set()  # Different case
        assert service.get_addr_keys("MOTOR1") == set()  # Different case

    def test_get_addr_keys_insensitive(self):
        """get_addr_keys_insensitive matches any case."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        assert service.get_addr_keys_insensitive("Motor1") == {rows[0].addr_key}
        assert service.get_addr_keys_insensitive("motor1") == {rows[0].addr_key}
        assert service.get_addr_keys_insensitive("MOTOR1") == {rows[0].addr_key}
        assert service.get_addr_keys_insensitive("MoToR1") == {rows[0].addr_key}

    def test_case_variations_indexed_together(self):
        """Different case variations of same name map to same lowercase entry."""
        service = NicknameIndexService()
        rows = [
            AddressRow(memory_type="X", address=1, nickname="Motor1"),
            AddressRow(memory_type="X", address=2, nickname="motor1"),  # Same lowercase
        ]
        service.rebuild_index(rows)

        # Exact case lookups return single row each
        assert service.get_addr_keys("Motor1") == {rows[0].addr_key}
        assert service.get_addr_keys("motor1") == {rows[1].addr_key}

        # Case-insensitive returns both
        assert service.get_addr_keys_insensitive("motor1") == {
            rows[0].addr_key,
            rows[1].addr_key,
        }


class TestNicknameIndexServiceDuplicateDetection:
    """Tests for is_duplicate method."""

    def test_is_duplicate_empty_nickname(self):
        """Empty nickname is never a duplicate."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        assert service.is_duplicate("", rows[0].addr_key) is False

    def test_is_duplicate_unique_nickname(self):
        """Unique nickname is not a duplicate."""
        service = NicknameIndexService()
        rows = [
            AddressRow(memory_type="X", address=1, nickname="Motor1"),
            AddressRow(memory_type="X", address=2, nickname="Motor2"),
        ]
        service.rebuild_index(rows)

        # Motor1 at addr 1 is not a duplicate (only one exists)
        assert service.is_duplicate("Motor1", rows[0].addr_key) is False

    def test_is_duplicate_same_nickname_same_address(self):
        """Same nickname at same address is not a duplicate."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        # Checking if Motor1 is duplicate while excluding the row that has it
        assert service.is_duplicate("Motor1", rows[0].addr_key) is False

    def test_is_duplicate_same_nickname_different_address(self):
        """Same nickname at different address is a duplicate."""
        service = NicknameIndexService()
        rows = [
            AddressRow(memory_type="X", address=1, nickname="Motor1"),
            AddressRow(memory_type="X", address=2, nickname="Motor1"),  # Duplicate!
        ]
        service.rebuild_index(rows)

        # Motor1 is duplicate for either address
        assert service.is_duplicate("Motor1", rows[0].addr_key) is True
        assert service.is_duplicate("Motor1", rows[1].addr_key) is True

    def test_is_duplicate_case_insensitive(self):
        """Duplicate detection is case-insensitive."""
        service = NicknameIndexService()
        rows = [
            AddressRow(memory_type="X", address=1, nickname="Motor1"),
            AddressRow(memory_type="X", address=2, nickname="motor1"),  # Different case
        ]
        service.rebuild_index(rows)

        # These are duplicates (CLICK treats nicknames case-insensitively)
        assert service.is_duplicate("Motor1", rows[0].addr_key) is True
        assert service.is_duplicate("motor1", rows[1].addr_key) is True
        assert service.is_duplicate("MOTOR1", rows[0].addr_key) is True

    def test_is_duplicate_new_nickname(self):
        """Check duplicate for nickname not in index."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        # NewName doesn't exist, so not a duplicate
        assert service.is_duplicate("NewName", 999) is False

        # But Motor1 exists, so using it at new address is duplicate
        assert service.is_duplicate("Motor1", 999) is True


class TestNicknameIndexServiceUpdate:
    """Tests for update method (incremental index updates)."""

    def test_update_add_new_nickname(self):
        """Update adds new nickname to index."""
        service = NicknameIndexService()
        service.rebuild_index([])  # Start empty

        addr_key = 0x0000001  # X1
        service.update(addr_key, "", "Motor1")

        assert service.get_addr_keys("Motor1") == {addr_key}
        assert service.get_addr_keys_insensitive("motor1") == {addr_key}

    def test_update_remove_nickname(self):
        """Update removes nickname from index."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        service.update(rows[0].addr_key, "Motor1", "")

        assert service.get_addr_keys("Motor1") == set()
        assert service.get_addr_keys_insensitive("motor1") == set()

    def test_update_rename_nickname(self):
        """Update handles rename (remove old, add new)."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="OldName")]
        service.rebuild_index(rows)

        service.update(rows[0].addr_key, "OldName", "NewName")

        assert service.get_addr_keys("OldName") == set()
        assert service.get_addr_keys("NewName") == {rows[0].addr_key}

    def test_update_preserves_other_entries(self):
        """Update doesn't affect other nicknames."""
        service = NicknameIndexService()
        rows = [
            AddressRow(memory_type="X", address=1, nickname="Motor1"),
            AddressRow(memory_type="X", address=2, nickname="Motor2"),
        ]
        service.rebuild_index(rows)

        # Rename Motor1 to Motor1New
        service.update(rows[0].addr_key, "Motor1", "Motor1New")

        # Motor2 unchanged
        assert service.get_addr_keys("Motor2") == {rows[1].addr_key}

    def test_update_handles_duplicate_nickname(self):
        """Update correctly handles adding duplicate nickname."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        # Add same nickname at different address
        addr_key_2 = 0x0000002  # X2
        service.update(addr_key_2, "", "Motor1")

        # Both should be in case-insensitive index
        assert service.get_addr_keys_insensitive("motor1") == {
            rows[0].addr_key,
            addr_key_2,
        }
        # Now it's a duplicate
        assert service.is_duplicate("Motor1", 999) is True

    def test_update_cleans_empty_sets(self):
        """Update removes empty sets from index."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        # Remove the only nickname
        service.update(rows[0].addr_key, "Motor1", "")

        # Internal implementation detail: empty sets should be cleaned up
        # We can verify by checking lookup returns empty set (not KeyError)
        assert service.get_addr_keys("Motor1") == set()


class TestNicknameIndexServiceReturnsCopies:
    """Tests that lookup methods return copies, not references."""

    def test_get_addr_keys_returns_copy(self):
        """get_addr_keys returns a copy, not internal set."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        result = service.get_addr_keys("Motor1")
        result.add(999)  # Modify the returned set

        # Internal state unchanged
        assert service.get_addr_keys("Motor1") == {rows[0].addr_key}

    def test_get_addr_keys_insensitive_returns_copy(self):
        """get_addr_keys_insensitive returns a copy, not internal set."""
        service = NicknameIndexService()
        rows = [AddressRow(memory_type="X", address=1, nickname="Motor1")]
        service.rebuild_index(rows)

        result = service.get_addr_keys_insensitive("motor1")
        result.add(999)  # Modify the returned set

        # Internal state unchanged
        assert service.get_addr_keys_insensitive("motor1") == {rows[0].addr_key}
