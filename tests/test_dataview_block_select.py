"""Tests for Dataview block-select pairing guard behavior."""

from clicknick.views.dataview_editor.window import DataviewEditorWindow


class TestDataviewPairedPromptType:
    def test_single_type_t_prompts_for_td(self):
        result = DataviewEditorWindow._get_paired_prompt_type([("T", 1), ("T", 2)])
        assert result == ("T", "TD")

    def test_single_type_ct_prompts_for_ctd(self):
        result = DataviewEditorWindow._get_paired_prompt_type([("CT", 1), ("CT", 2)])
        assert result == ("CT", "CTD")

    def test_mixed_types_do_not_prompt(self):
        assert DataviewEditorWindow._get_paired_prompt_type([("T", 1), ("TD", 1)]) is None
        assert DataviewEditorWindow._get_paired_prompt_type([("T", 1), ("X", 1)]) is None

    def test_non_timer_types_do_not_prompt(self):
        assert DataviewEditorWindow._get_paired_prompt_type([("X", 1)]) is None
