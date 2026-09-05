"""Check Program preferences survive restarts without affecting validation."""

import json

import pytest

from clicknick.services.program_check_preferences import (
    ProgramCheckPreferences,
    default_preferences_path,
)


def test_preferences_use_existing_appdata_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_preferences_path() == tmp_path / "ClickNick" / "check-program.json"


def test_expansion_survives_restart_and_other_windows(tmp_path):
    path = tmp_path / "ClickNick" / "check-program.json"
    first = ProgramCheckPreferences(path)
    assert first.is_expanded("RUNG_CONTRADICTION")
    assert first.set_expanded("RUNG_CONTRADICTION", False)
    second = ProgramCheckPreferences(path)
    assert not second.is_expanded("RUNG_CONTRADICTION")
    assert first.set_expanded("RUNG_CONTRADICTION", True)
    assert second.set_expanded("CMP_ALWAYS_TRUE", False)
    reopened = ProgramCheckPreferences(path)
    assert reopened.is_expanded("RUNG_CONTRADICTION")
    assert not reopened.is_expanded("CMP_ALWAYS_TRUE")
    assert reopened.is_expanded("NEW_RULE")


@pytest.mark.parametrize("contents", ["not json", "[]", "null", '{"expanded": []}'])
def test_invalid_preferences_fall_back_to_defaults(tmp_path, contents):
    path = tmp_path / "check-program.json"
    path.write_text(contents, encoding="utf-8")
    prefs = ProgramCheckPreferences(path)
    assert prefs.is_expanded("RULE")
    assert prefs.set_expanded("RULE", False)
    assert json.loads(path.read_text())["expanded"] == {"RULE": False}


def test_invalid_states_do_not_hide_findings(tmp_path):
    path = tmp_path / "check-program.json"
    path.write_text('{"expanded": {"RULE": "false", "OTHER": false}}', encoding="utf-8")
    prefs = ProgramCheckPreferences(path)
    assert prefs.is_expanded("RULE")
    assert not prefs.is_expanded("OTHER")


def test_write_failure_keeps_choice_in_memory(tmp_path):
    parent = tmp_path / "not-a-directory"
    parent.write_text("file", encoding="utf-8")
    prefs = ProgramCheckPreferences(parent / "check-program.json")
    assert not prefs.set_expanded("RULE", False)
    assert not prefs.is_expanded("RULE")
