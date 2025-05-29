from clicknick.filters import ContainsFilter


class TestContainsFilter:
    def test_uppercase_word_boundaries(self):
        """Test that uppercase boundaries rank higher than buried matches"""
        filter_obj = ContainsFilter()

        # Test searching for "data" - should rank CamelCase boundaries higher
        completion_list = [
            "metadata",  # "data" buried in middle (other_matches)
            "parseData",  # "Data" at uppercase boundary (word_start_matches)
            "User Data",  # "Data" at space boundary (word_start_matches)
            "mandatary",  # "data" buried in middle (other_matches)
            "update_data",  # "data" after underscore (word_start_matches)
            "validate",  # "data" doesn't exist
            "data_file",  # "data" at start (word_start_matches)
        ]

        result = filter_obj.filter_matches(completion_list, "data")

        # Should find 6 matches (validate has no "data")
        assert len(result) == 6
        assert "validate" not in result

        # Word boundary matches should come first
        word_boundary_expected = {"parseData", "User Data", "update_data", "data_file"}
        buried_expected = {"metadata", "mandatary"}

        # Check the grouping
        assert set(result[:4]) == word_boundary_expected
        assert set(result[4:]) == buried_expected
