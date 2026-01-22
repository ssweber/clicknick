"""Unit tests for MutableRowBuilder."""

from clicknick.models.address_row import AddressRow
from clicknick.models.mutable_row_builder import MutableRowBuilder


class TestMutableRowBuilderBasics:
    """Basic tests for MutableRowBuilder."""

    def test_empty_builder(self):
        """Empty builder has no changes."""
        builder = MutableRowBuilder()
        assert builder.has_changes() is False

    def test_builder_with_nickname(self):
        """Builder with nickname set has changes."""
        builder = MutableRowBuilder()
        builder.nickname = "NewName"
        assert builder.has_changes() is True

    def test_builder_with_multiple_fields(self):
        """Builder with multiple fields set."""
        builder = MutableRowBuilder(
            nickname="Motor1",
            comment="Main motor",
            initial_value="100",
            retentive=True,
        )
        assert builder.has_changes() is True
        assert builder.nickname == "Motor1"
        assert builder.comment == "Main motor"
        assert builder.initial_value == "100"
        assert builder.retentive is True


class TestMutableRowBuilderFreeze:
    """Tests for MutableRowBuilder.freeze()."""

    def test_freeze_applies_nickname(self):
        """Freeze applies nickname change to base row."""
        base = AddressRow(memory_type="X", address=1, nickname="OldName")
        builder = MutableRowBuilder(nickname="NewName")

        result = builder.freeze(base)

        assert result.nickname == "NewName"
        assert result.memory_type == "X"
        assert result.address == 1
        # Original row unchanged
        assert base.nickname == "OldName"

    def test_freeze_applies_multiple_fields(self):
        """Freeze applies multiple field changes."""
        base = AddressRow(memory_type="DS", address=1)
        builder = MutableRowBuilder(
            nickname="Motor1",
            comment="Main motor",
            initial_value="100",
            retentive=True,
        )

        result = builder.freeze(base)

        assert result.nickname == "Motor1"
        assert result.comment == "Main motor"
        assert result.initial_value == "100"
        assert result.retentive is True

    def test_freeze_preserves_unset_fields(self):
        """Freeze preserves fields not set in builder."""
        base = AddressRow(
            memory_type="X",
            address=1,
            nickname="OriginalName",
            comment="Original comment",
            initial_value="1",
            retentive=True,
        )
        builder = MutableRowBuilder(nickname="NewName")

        result = builder.freeze(base)

        assert result.nickname == "NewName"
        assert result.comment == "Original comment"
        assert result.initial_value == "1"
        assert result.retentive is True

    def test_freeze_empty_builder_returns_base(self):
        """Freeze with no changes returns base row."""
        base = AddressRow(memory_type="X", address=1, nickname="Name")
        builder = MutableRowBuilder()

        result = builder.freeze(base)

        assert result is base


class TestMutableRowBuilderFieldAccess:
    """Tests for field access methods."""

    def test_get_field(self):
        """Get field by name."""
        builder = MutableRowBuilder(nickname="Test", comment="Comment")

        assert builder.get_field("nickname") == "Test"
        assert builder.get_field("comment") == "Comment"
        assert builder.get_field("initial_value") is None
        assert builder.get_field("retentive") is None

    def test_set_field(self):
        """Set field by name."""
        builder = MutableRowBuilder()
        builder.set_field("nickname", "Test")
        builder.set_field("comment", "Comment")
        builder.set_field("retentive", True)

        assert builder.nickname == "Test"
        assert builder.comment == "Comment"
        assert builder.retentive is True

    def test_set_field_unknown_name(self):
        """Set field with unknown name adds attribute (Python dataclass behavior)."""
        builder = MutableRowBuilder()
        # Python dataclasses allow setting any attribute
        builder.set_field("unknown_field", "value")
        assert builder.unknown_field == "value"
        # But has_changes only checks known fields
        builder2 = MutableRowBuilder()
        builder2.set_field("unknown_field", "value")
        assert builder2.has_changes() is False


class TestMutableRowBuilderCopy:
    """Tests for builder copy functionality."""

    def test_copy_creates_independent_builder(self):
        """Copy creates independent builder."""
        original = MutableRowBuilder(nickname="Name1", comment="Comment1")
        copied = original.copy()

        # Modify original
        original.nickname = "Name2"

        # Copy should be unchanged
        assert copied.nickname == "Name1"
        assert copied.comment == "Comment1"

    def test_copy_all_fields(self):
        """Copy preserves all fields."""
        original = MutableRowBuilder(
            nickname="Name",
            comment="Comment",
            initial_value="100",
            retentive=True,
        )
        copied = original.copy()

        assert copied.nickname == original.nickname
        assert copied.comment == original.comment
        assert copied.initial_value == original.initial_value
        assert copied.retentive == original.retentive
