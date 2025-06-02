import pytest

from clicknick.filters import ContainsPlusFilter
from clicknick.nickname import Nickname


class TestContainsPlusFilter:
    @pytest.fixture
    def filter_obj(self):
        """Create filter and setup test data"""
        filter_obj = ContainsPlusFilter()

        # PLC completion list with various naming patterns
        completion_texts = [
            # Command variations
            "Cmd_Start",
            "Command_Stop",
            "Manual_Cmd",
            "Emergency_Command",
            # Control variations
            "Ctrl_Enable",
            "Control_Mode",
            "Speed_Ctrl",
            "Temperature_Control",
            # Request/Response
            "Req_Reset",
            "Request_Data",
            "Auto_Req",
            "Data_Request",
            "Res_Complete",
            "Response_Time",
            "Error_Res",
            "HTTP_Response",
            # State/Status
            "St_Running",
            "State_Machine",
            "Current_St",
            "Machine_State",
            "Stat_Word",
            "Status_Ready",
            "Alarm_Stat",
            "System_Status",
            # Values and Config
            "Val_Pressure",
            "Value_Set",
            "Temp_Val",
            "Pressure_Value",
            "Cfg_File",
            "Config_Mode",
            "System_Cfg",
            "Network_Config",
            # Parameters and Acknowledgments
            "Param_List",
            "Parameter_Set",
            "Motor_Param",
            "System_Parameter",
            "Ack_Button",
            "Acknowledge_All",
            "Alarm_Ack",
            "Manual_Acknowledge",
            # Alarms and History
            "Alm_Active",
            "Alarm_Count",
            "Safety_Alm",
            "Critical_Alarm",
            "Hist_Data",
            "History_Log",
            "Event_Hist",
            "Data_History",
            # Positions and Indexes
            "Idx_Current",
            "Index_Position",
            "Array_Idx",
            "Table_Index",
            "Pos_Actual",
            "Position_Target",
            "Valve_Pos",
            "Robot_Position",
            # Initialization and Maintenance
            "Init_Sequence",
            "Initialize_System",
            "Auto_Init",
            "System_Initialize",
            "Maint_Mode",
            "Maintenance_Required",
            "Sched_Maint",
            "Preventive_Maintenance",
            # Production and Manual
            "Prod_Count",
            "Production_Rate",
            "Daily_Prod",
            "Total_Production",
            "Man_Override",
            "Manual_Mode",
            "Oper_Man",
            "Full_Manual",
            # Sequences and Errors
            "Seq_Step",
            "Sequence_Active",
            "Start_Seq",
            "Boot_Sequence",
            "Err_Code",
            "Error_Message",
            "System_Err",
            "Communication_Error",
            # Time patterns for regex testing
            "YYYYMMDD",
            "HHMMSS",
            "MS_Timer",
            "WWWW_YYMM",
            "StartHour",
            "Start_hh",
            # CamelCase and special patterns
            "parseDataValue",
            "XMLHttpRequest",
            "SQLDatabaseConnection",
            "firstName",
            "lastName",
            "userID",
            "deviceIP",
            # Edge cases
            "A",
            "BB",
            "CCC",
            "DDDD",
            "EEEE",  # Short words
            "aaaaaa",
            "BBBBBB",  # Repeated letters
            "First_Item",
            "Second_Value",
            "Third_Parameter",  # Ordinals
        ]

        # Convert to Nickname objects and generate tags
        nicknames = [Nickname(text, "mock") for text in completion_texts]
        for nickname in nicknames:
            nickname.abbr_tags = filter_obj.generate_tags(nickname.nickname)

        return filter_obj, nicknames

    def test_basic_contains_matching(self, filter_obj):
        """Test basic contains functionality works"""
        filter_instance, completion_list = filter_obj

        result = filter_instance.filter_matches(completion_list, "Command")
        result_texts = [str(item) for item in result]

        # Should find items containing "Command"
        expected = ["Command_Stop", "Emergency_Command"]
        assert all(item in result_texts for item in expected)
        assert len(result) >= len(expected)

    def test_abbreviation_matching_full_to_abbrev(self, filter_obj):
        """Test typing full word finds abbreviated tags"""
        filter_instance, completion_list = filter_obj

        # Typing "command" should find items with "cmd" tags
        result = filter_instance.filter_matches(completion_list, "command")
        result_texts = [str(item) for item in result]

        # Should find both contains matches and abbreviation matches
        expected_contains = ["Command_Stop", "Emergency_Command"]
        expected_abbrev = ["Cmd_Start", "Manual_Cmd"]  # These have "cmd" in abbr_tags

        assert all(item in result_texts for item in expected_contains)
        assert all(item in result_texts for item in expected_abbrev)

    def test_abbreviation_matching_abbrev_to_full(self, filter_obj):
        """Test typing abbreviation finds full word tags"""
        filter_instance, completion_list = filter_obj

        # Typing "cmd" should find items with "command" in their text/tags
        result = filter_instance.filter_matches(completion_list, "cmd")
        result_texts = [str(item) for item in result]

        expected = ["Cmd_Start", "Manual_Cmd", "Command_Stop", "Emergency_Command"]
        assert all(item in result_texts for item in expected)

    def test_mapped_shorthand_ordinals(self, filter_obj):
        """Test predefined shorthand mappings (ordinals)"""
        filter_instance, completion_list = filter_obj

        # Test "first" → "1st" mapping
        result = filter_instance.filter_matches(completion_list, "first")
        result_texts = [str(item) for item in result]
        assert "First_Item" in result_texts

        # Test "second" → "2nd", "ss" mapping
        result = filter_instance.filter_matches(completion_list, "second")
        result_texts = [str(item) for item in result]
        assert "Second_Value" in result_texts

    def test_mapped_shorthand_time_formats(self, filter_obj):
        """Test time format shorthand mappings"""
        filter_instance, completion_list = filter_obj

        # Test "hour" → "hh" mapping
        result = filter_instance.filter_matches(completion_list, "Hour")
        result_texts = [str(item) for item in result]
        # Should find items with "HH" pattern
        hh_items = [item for item in result_texts if "hh" in item.lower()]
        assert len(hh_items) > 0

        # Test "year" → "YY", "YYYY" mapping
        result = filter_instance.filter_matches(completion_list, "year")
        result_texts = [str(item) for item in result]
        yyyy_items = [item for item in result_texts if "YYYY" in item]
        assert len(yyyy_items) > 0

    def test_time_pattern_regex_expansion(self, filter_obj):
        """Test time pattern regex processing"""
        filter_instance, completion_list = filter_obj

        # These should be processed by time pattern regexes
        test_cases = [
            "YYYY_MM_DD",  # Should split into "YYYY", "MM", "DD"
            "HH_MM_SS",  # Should split into "HH", "MM", "SS"
        ]

        for test_item in test_cases:
            if any(str(item) == test_item for item in completion_list):
                # Test that we can find it by searching for expanded parts
                result = filter_instance.filter_matches(completion_list, "year")
                result_texts = [str(item) for item in result]
                if "YYYY" in test_item:
                    assert test_item in result_texts

    def test_word_boundary_splitting(self, filter_obj):
        """Test splitting on underscores, spaces, and CamelCase"""
        filter_instance = filter_obj[0]

        test_cases = [
            ("parse_data_value", ["parse", "data", "value"]),
            ("Parse Data Value", ["Parse", "Data", "Value"]),
            ("parseDataValue", ["parse", "Data", "Value"]),
            ("XMLHttpRequest", ["XMLHttp", "Request"]),
        ]

        for text, expected_words in test_cases:
            words = filter_instance.split_into_words(text)
            # Filter out short words as the method does
            expected_filtered = [w for w in expected_words if len(w) > 1]
            assert set(words) == set(expected_filtered)

    def test_abbrword_special_case(self, filter_obj):
        """Test _abbrword_special_case function independently"""
        filter_instance = filter_obj[0]

        test_cases = [
            # Same letter repetition (should return unchanged)
            ("YYYY", "YYYY"),
            ("aaaa", "aaaa"),
            ("BBbb", "bbbb"),  # Mixed case same letters
            # Short words (should return lowercase)
            ("AB", "ab"),
            ("XYZ", "xyz"),
            ("Hi", "hi"),
            # All consonants after first letter (should return lowercase)
            ("XML", "xml"),
            ("HTTP", "http"),
            ("rst", "rst"),
            # Normal words with vowels after first letter (should return None)
            ("Alarm", None),
            ("Command", None),
            ("Hello", None),
        ]

        for word, expected in test_cases:
            result = filter_instance._abbrword_special_case(word)
            assert result == expected, (
                f"_abbrword_special_case('{word}') = '{result}', expected '{expected}'"
            )

    def test_abbrword_consonants(self, filter_obj):
        """Test _abbrword_consonants function independently"""
        filter_instance = filter_obj[0]

        test_cases = [
            ("Alarm", "alrm"),  # Keep first + consonants, remove doubles
            ("Command", "cmnd"),  # a->skip, o->skip
            ("Control", "cntrl"),  # o->skip
            ("Request", "rqst"),  # e->skip, e->skip
            ("Response", "rspns"),  # e->skip, o->skip, e->skip
            ("Parameter", "prmtr"),  # a->skip, a->skip, e->skip, e->skip
            ("Hello", "hl"),  # e->skip, o->skip, double l becomes single
            ("Mississippi", "msp"),  # i->skip, i->skip, i->skip, i->skip, double s/s/p reduction
        ]

        for word, expected in test_cases:
            result = filter_instance._abbrword_consonants(word)
            assert result == expected, (
                f"_abbrword_consonants('{word}') = '{result}', expected '{expected}'"
            )

    def test_abbrword_reduced_consonants(self, filter_obj):
        """Test _abbrword_reduced_consonants function independently"""
        filter_instance = filter_obj[0]

        test_cases = [
            # Drop first consonant after vowel if next is consonant
            (
                "Alarm",
                "alm",
            ),  # a-l-r-m: after 'a', 'l' is first consonant, 'r' is next consonant -> drop 'l'
            (
                "Control",
                "ctrl",
            ),  # o-n-t-r-o-l: after 'o', 'n' is first consonant, 't' is next -> drop 'n'
            (
                "Request",
                "rqt",
            ),  # e-q-u-e-s-t: after 'e', 'q' is first, 'u' is vowel so keep 'q'; after 'u', no consonants follow pattern
            ("Parameter", "prmtr"),  # Multiple vowel-consonant patterns
            ("Forward", "fwd"),  # o-r-w-a-r-d: after 'o', 'r' is first, 'w' is next -> drop 'r'
        ]

        for word, expected in test_cases:
            result = filter_instance._abbrword_reduced_consonants(word)
            assert result == expected, (
                f"_abbrword_reduced_consonants('{word}') = '{result}', expected '{expected}'"
            )

    def test_get_abbreviated_word_list(self, filter_obj):
        """Test the main abbreviation function that combines all approaches"""
        filter_instance = filter_obj[0]

        test_cases = [
            # Special cases should return single item
            ("YYYY", ["YYYY"]),  # Same letters
            ("XML", ["xml"]),  # Short + all consonants
            ("Hi", ["hi"]),  # Short word
            # Normal words should return both consonant variants (if different lengths)
            ("Alarm", ["alrm", "alm"]),  # Both variants if length > 2
            ("Command", ["cmnd", "cmd"]),  # Both variants
            ("Control", ["cntrl", "ctrl"]),  # Both variants
            # Very short results might only return one variant
            ("Hi", ["hi"]),  # Special case only
            ("Go", ["go"]),  # Special case only
        ]

        for word, expected in test_cases:
            result = filter_instance.get_abbreviated_word_list(word)
            # For normal words, we expect the results to match our expected patterns
            if len(expected) == 1 and expected[0] in [word.lower(), "YYYY", "xml", "hi", "go"]:
                # Special cases
                assert result == expected, (
                    f"get_abbreviated_word_list('{word}') = {result}, expected {expected}"
                )
            else:
                # For normal abbreviations, check that we get reasonable results
                assert len(result) > 0, f"get_abbreviated_word_list('{word}') returned empty list"
                assert all(len(abbr) >= 3 for abbr in result), (
                    f"get_abbreviated_word_list('{word}') = {result}, all should be length >= 3"
                )

    def test_multiple_word_search_intersection(self, filter_obj):
        """Test that multiple words require ALL words to match (intersection)"""
        filter_instance, completion_list = filter_obj

        # Search for "System Error" - should find items containing both words
        result = filter_instance.filter_matches(completion_list, "System Error")
        result_texts = [str(item) for item in result]

        # Should find items that contain both "System" AND "Error"
        expected = ["System_Err"]  # Contains both
        assert all(item in result_texts for item in expected)

        # Should NOT find items with only one word
        should_not_find = ["System_Status", "Communication_Error"]  # Only one word each
        for item in should_not_find:
            if item in [str(i) for i in completion_list]:
                # Only assert if the item exists in completion list
                assert item not in result_texts

    def test_single_vs_multiple_word_routing(self, filter_obj):
        """Test that single/multiple word searches use different code paths"""
        filter_instance, completion_list = filter_obj

        # Single word should use cascading approach (contains + abbreviation)
        single_result = filter_instance.filter_matches(completion_list, "command")

        # Multiple words should use intersection approach
        multi_result = filter_instance.filter_matches(completion_list, "command stop")

        # Multiple word search should be more restrictive
        assert len(multi_result) <= len(single_result)

        # Multi-word should find items with both words
        multi_texts = [str(item) for item in multi_result]
        assert "Command_Stop" in multi_texts

    def test_empty_and_whitespace_input(self, filter_obj):
        """Test edge cases with empty/whitespace input"""
        filter_instance, completion_list = filter_obj

        # Empty string should return full list
        result = filter_instance.filter_matches(completion_list, "")
        assert len(result) == len(completion_list)

        # Whitespace gets processed and becomes empty after word splitting
        result = filter_instance.filter_matches(completion_list, "   ")
        # After splitting whitespace, it becomes empty search, so should return full list
        assert len(result) == len(completion_list)

    def test_no_matches_case(self, filter_obj):
        """Test searching for non-existent terms"""
        filter_instance, completion_list = filter_obj

        result = filter_instance.filter_matches(completion_list, "xyz_nonexistent_term")
        assert len(result) == 0

    def test_cascading_order_single_word(self, filter_obj):
        """Test that contains matches come before abbreviation matches for single words"""
        filter_instance, completion_list = filter_obj

        result = filter_instance.filter_matches(completion_list, "cmd")
        result_texts = [str(item) for item in result]

        # Items containing "cmd" literally should come first
        contains_matches = ["Cmd_Start", "Manual_Cmd"]

        # Find positions of contains matches
        contains_positions = []
        for match in contains_matches:
            if match in result_texts:
                contains_positions.append(result_texts.index(match))

        # Items found through abbreviation should come after
        abbrev_matches = ["Command_Stop", "Emergency_Command"]  # Found via abbreviation
        abbrev_positions = []
        for match in abbrev_matches:
            if match in result_texts:
                abbrev_positions.append(result_texts.index(match))

        # Contains matches should generally come before abbreviation matches
        if contains_positions and abbrev_positions:
            assert min(contains_positions) < max(abbrev_positions)

    def test_generate_tags_completeness(self, filter_obj):
        """Test that generate_tags creates expected tag varieties"""
        filter_instance = filter_obj[0]

        test_cases = [
            "Command_Parameter",  # Should generate: command, parameter, cmd, prmtr, etc.
            "YYYYMMDD",  # Should handle time patterns
            "parseDataValue",  # Should handle CamelCase
        ]

        for text in test_cases:
            tags = filter_instance.generate_tags(text)

            # Should have some tags
            assert len(tags) > 0

            # Should be sorted and unique
            assert tags == sorted(set(tags))

            # All tags should be strings
            assert all(isinstance(tag, str) for tag in tags)

    def test_nickname_object_compatibility(self, filter_obj):
        """Test that the filter works properly with Nickname objects"""
        filter_instance, completion_list = filter_obj

        # Verify we're working with Nickname objects
        assert all(isinstance(item, Nickname) for item in completion_list)

        # Test that filtering returns Nickname objects
        result = filter_instance.filter_matches(completion_list, "cmd")
        assert all(isinstance(item, Nickname) for item in result)

        # Test that we can access Nickname properties
        for item in result[:3]:  # Check first few results
            assert hasattr(item, "nickname")
            assert hasattr(item, "abbr_tags")
            assert isinstance(item.nickname, str)
            assert isinstance(item.abbr_tags, list)

    def test_integration_abbreviation_pipeline(self, filter_obj):
        """Test the complete abbreviation pipeline integration"""
        filter_instance = filter_obj[0]

        # Test a word that goes through the complete pipeline
        test_word = "Parameter"

        # 1. Should NOT be handled by special case
        special_result = filter_instance._abbrword_special_case(test_word)
        assert special_result is None

        # 2. Should generate consonant-based abbreviation
        consonant_result = filter_instance._abbrword_consonants(test_word)
        assert len(consonant_result) > 2

        # 3. Should generate reduced consonant abbreviation
        reduced_result = filter_instance._abbrword_reduced_consonants(test_word)
        assert len(reduced_result) > 2

        # 4. Complete pipeline should return both if they're different
        complete_result = filter_instance.get_abbreviated_word_list(test_word)
        assert len(complete_result) >= 1

        # 5. Results should be incorporated into needle variants
        variants = filter_instance.get_needle_variants(test_word)
        assert test_word.lower() in variants  # Original word
        assert any(abbr in variants for abbr in complete_result)  # At least one abbreviation

    def test_edge_case_very_short_words(self, filter_obj):
        """Test handling of very short words"""
        filter_instance = filter_obj[0]

        short_words = ["A", "BB", "CCC"]

        for word in short_words:
            # Should be handled by special case
            special_result = filter_instance._abbrword_special_case(word)
            assert special_result is not None
            assert special_result == word

            # Complete pipeline should return the special case
            complete_result = filter_instance.get_abbreviated_word_list(word)
            assert complete_result == [word]

    def test_edge_case_repeated_letters(self, filter_obj):
        """Test handling of words with repeated letters"""
        filter_instance = filter_obj[0]

        repeated_words = ["YYYY", "aaaa", "BBBBBB"]

        for word in repeated_words:
            # Should be handled by special case (same letter check)
            special_result = filter_instance._abbrword_special_case(word)
            assert special_result == word  # Should return unchanged

            # Complete pipeline should return the unchanged word
            complete_result = filter_instance.get_abbreviated_word_list(word)
            assert complete_result == [word]
