from clicknick.utils.filters import ContainsFilter, parse_analysis_prefix


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


class TestParseAnalysisPrefix:
    def test_no_prefix(self):
        assert parse_analysis_prefix("^Alm") == (None, None, "^Alm")

    def test_plain_text(self):
        assert parse_analysis_prefix("motor") == (None, None, "motor")

    def test_empty(self):
        assert parse_analysis_prefix("") == (None, None, "")

    def test_input_prefix_alone(self):
        assert parse_analysis_prefix("input:") == ("input", None, "")

    def test_output_prefix_alone(self):
        assert parse_analysis_prefix("output:") == ("output", None, "")

    def test_pivot_prefix_alone(self):
        assert parse_analysis_prefix("pivot:") == ("pivot", None, "")

    def test_isolated_prefix_alone(self):
        assert parse_analysis_prefix("isolated:") == ("isolated", None, "")

    def test_role_prefix_with_text(self):
        assert parse_analysis_prefix("input: pump") == ("input", None, "pump")

    def test_role_prefix_with_anchor(self):
        assert parse_analysis_prefix("input: ^Alm") == ("input", None, "^Alm")

    def test_upstream_with_tag(self):
        assert parse_analysis_prefix("upstream:MotorOut") == ("upstream", "MotorOut", "")

    def test_downstream_with_tag(self):
        assert parse_analysis_prefix("downstream:PumpRun") == ("downstream", "PumpRun", "")

    def test_upstream_with_tag_and_text(self):
        assert parse_analysis_prefix("upstream:MotorOut ^Alm") == ("upstream", "MotorOut", "^Alm")

    def test_downstream_with_tag_and_text(self):
        assert parse_analysis_prefix("downstream:X001 pump") == ("downstream", "X001", "pump")

    def test_upstream_no_arg(self):
        assert parse_analysis_prefix("upstream:") == ("upstream", None, "")

    def test_case_insensitive_prefix(self):
        assert parse_analysis_prefix("INPUT: motor") == ("input", None, "motor")
        assert parse_analysis_prefix("Upstream:Tag") == ("upstream", "Tag", "")

    def test_leading_whitespace(self):
        assert parse_analysis_prefix("  input:") == ("input", None, "")

    def test_not_a_prefix(self):
        assert parse_analysis_prefix("inputting") == (None, None, "inputting")
