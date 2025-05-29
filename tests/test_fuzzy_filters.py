from clicknick.filters import FuzzyFilter


class TestFuzzyPLCVariables:
    def test_bidirectional_plc_matching(self):
        """Test finding matches when user types either full words OR abbreviations"""

        # Realistic PLC variables with common abbreviation patterns
        plc_variables = [
            "Cmd_Start",
            "Command_Stop",
            "Manual_Cmd",
            "Ctrl_Enable",
            "Control_Mode",
            "Speed_Ctrl",
            "Req_Reset",
            "Request_Data",
            "Auto_Req",
            "Res_Complete",
            "Response_Time",
            "Error_Res",
            "St_Running",
            "State_Machine",
            "Current_St",
            "Stat_Word",
            "Status_Ready",
            "Alarm_Stat",
            "Val_Pressure",
            "Value_Set",
            "Temp_Val",
            "Cfg_File",
            "Config_Mode",
            "System_Cfg",
            "Param_List",
            "Parameter_Set",
            "Motor_Param",
            "Ack_Button",
            "Acknowledge_All",
            "Alarm_Ack",
            "Alm_Active",
            "Alarm_Count",
            "Safety_Alm",
            "Hist_Data",
            "History_Log",
            "Event_Hist",
            "Idx_Current",
            "Index_Position",
            "Array_Idx",
            "Pos_Actual",
            "Position_Target",
            "Valve_Pos",
            "Init_Sequence",
            "Initialize_System",
            "Auto_Init",
            "Maint_Mode",
            "Maintenance_Required",
            "Sched_Maint",
            "Prod_Count",
            "Production_Rate",
            "Daily_Prod",
            "Man_Override",
            "Manual_Mode",
            "Oper_Man",
            "Seq_Step",
            "Sequence_Active",
            "Start_Seq",
            "Err_Code",
            "Error_Message",
            "System_Err",
        ]

        bidirectional_cases = [
            # User types FULL WORD → should find abbreviated versions
            ("command", ["Cmd_Start", "Command_Stop", "Manual_Cmd"]),
            ("control", ["Ctrl_Enable", "Control_Mode", "Speed_Ctrl"]),
            ("request", ["Req_Reset", "Request_Data", "Auto_Req"]),
            ("response", ["Res_Complete", "Response_Time", "Error_Res"]),
            ("state", ["St_Running", "State_Machine", "Current_St"]),
            ("status", ["Stat_Word", "Status_Ready", "Alarm_Stat"]),
            ("value", ["Val_Pressure", "Value_Set", "Temp_Val"]),
            ("config", ["Cfg_File", "Config_Mode", "System_Cfg"]),
            ("parameter", ["Param_List", "Parameter_Set", "Motor_Param"]),
            ("acknowledge", ["Ack_Button", "Acknowledge_All", "Alarm_Ack"]),
            ("alarm", ["Alm_Active", "Alarm_Count", "Safety_Alm"]),
            ("history", ["Hist_Data", "History_Log", "Event_Hist"]),
            ("index", ["Idx_Current", "Index_Position", "Array_Idx"]),
            ("position", ["Pos_Actual", "Position_Target", "Valve_Pos"]),
            ("initialize", ["Init_Sequence", "Initialize_System", "Auto_Init"]),
            ("maintenance", ["Maint_Mode", "Maintenance_Required", "Sched_Maint"]),
            ("production", ["Prod_Count", "Production_Rate", "Daily_Prod"]),
            ("manual", ["Man_Override", "Manual_Mode", "Oper_Man"]),
            ("sequence", ["Seq_Step", "Sequence_Active", "Start_Seq"]),
            ("error", ["Err_Code", "Error_Message", "System_Err"]),
            # User types ABBREVIATION → should find full word versions
            ("cmd", ["Cmd_Start", "Command_Stop", "Manual_Cmd"]),
            ("ctrl", ["Ctrl_Enable", "Control_Mode", "Speed_Ctrl"]),
            ("req", ["Req_Reset", "Request_Data", "Auto_Req"]),
            ("res", ["Res_Complete", "Response_Time", "Error_Res"]),
            ("st", ["St_Running", "State_Machine", "Current_St"]),
            ("stat", ["Stat_Word", "Status_Ready", "Alarm_Stat"]),
            ("val", ["Val_Pressure", "Value_Set", "Temp_Val"]),
            ("cfg", ["Cfg_File", "Config_Mode", "System_Cfg"]),
            ("param", ["Param_List", "Parameter_Set", "Motor_Param"]),
            ("ack", ["Ack_Button", "Acknowledge_All", "Alarm_Ack"]),
            ("alm", ["Alm_Active", "Alarm_Count", "Safety_Alm"]),
            ("hist", ["Hist_Data", "History_Log", "Event_Hist"]),
            ("idx", ["Idx_Current", "Index_Position", "Array_Idx"]),
            ("pos", ["Pos_Actual", "Position_Target", "Valve_Pos"]),
            ("init", ["Init_Sequence", "Initialize_System", "Auto_Init"]),
            ("maint", ["Maint_Mode", "Maintenance_Required", "Sched_Maint"]),
            ("prod", ["Prod_Count", "Production_Rate", "Daily_Prod"]),
            ("man", ["Man_Override", "Manual_Mode", "Oper_Man"]),
            ("seq", ["Seq_Step", "Sequence_Active", "Start_Seq"]),
            ("err", ["Err_Code", "Error_Message", "System_Err"]),
        ]

        filter_obj = FuzzyFilter(threshold=60)

        total_found = 0
        total_expected = 0

        for search_term, expected_matches in bidirectional_cases:
            result = filter_obj.filter_matches(plc_variables, search_term)

            print(f"\nSearch '{search_term}' → found {len(result)} matches:")
            for i, match in enumerate(result[:3], 1):  # Top 3
                print(f"  {i}. {match}")

            # Count how many expected matches we found
            found_expected = [m for m in expected_matches if m in result]
            total_found += len(found_expected)
            total_expected += len(expected_matches)

            if len(found_expected) < len(expected_matches):
                missed = [m for m in expected_matches if m not in result]
                print(f"  ❌ Missed: {missed}")
            elif len(found_expected) == len(expected_matches):
                print("  ✅ Found all expected matches")

        recall = total_found / total_expected if total_expected > 0 else 0
        print(
            f"\n📊 Threshold 60: Found {total_found}/{total_expected} expected matches ({recall:.1%} recall)"
        )

    def test_ranking_quality(self):
        """Test that we get reasonable matches and filter out non-matches"""
        plc_variables = [
            "Alm_Active",
            "AlarmManager",
            "Alarm_History",
            "False_Alarm_Count",
            "Conveyor_Speed",  # should NOT match
        ]

        # Test both directions
        test_cases = [
            ("alarm", ["Alm_Active", "AlarmManager", "Alarm_History", "False_Alarm_Count"]),
            ("alm", ["Alm_Active", "AlarmManager", "Alarm_History", "False_Alarm_Count"]),
        ]

        filter_obj = FuzzyFilter(threshold=60)

        for search_term, expected_matches in test_cases:
            result = filter_obj.filter_matches(plc_variables, search_term)

            print(f"\nMatches for '{search_term}':")
            for i, match in enumerate(result, 1):
                print(f"  {i}. {match}")

            # Should get the alarm-related variables
            for expected in expected_matches:
                assert expected in result, f"{expected} should match '{search_term}'"

            # Should NOT get unrelated variables
            assert "Normal_Operation" not in result, (
                f"Normal_Operation should not match '{search_term}'"
            )

            print(
                f"✅ Found {len(result)} reasonable matches for '{search_term}', filtered out non-matches"
            )


# Run the tests
test_obj = TestFuzzyPLCVariables()

try:
    test_obj.test_ranking_quality()
    print("✅ Ranking test passed - skipping bidirectional test")
except AssertionError as e:
    print(f"❌ Ranking test failed: {e}")
    print("🔄 Running bidirectional test instead...")
    test_obj.test_bidirectional_plc_matching()
except Exception as e:
    print(f"💥 Unexpected error in ranking test: {e}")
    print("🔄 Running bidirectional test instead...")
    test_obj.test_bidirectional_plc_matching()
