"""ClickNick's settings file: Redraw Ladder on Sync and its one-time notice."""

from __future__ import annotations

import json
import logging

import pytest

from clicknick.config import AppSettings
from clicknick.services import settings_file
from clicknick.services.settings_file import SavedSettings, read_settings, write_settings


@pytest.mark.parametrize(
    "saved",
    [
        SavedSettings(),
        SavedSettings(redraw_on_sync=False),
        SavedSettings(redraw_on_sync=True, redraw_notice_shown=True),
        SavedSettings(redraw_notice_shown=True),
    ],
)
def test_written_settings_read_back(tmp_path, saved) -> None:
    path = tmp_path / "ClickNick" / "settings.json"

    assert write_settings(saved, path)

    assert read_settings(path) == saved
    assert not path.with_suffix(".json.staging").exists()


def test_the_file_holds_only_what_was_set(tmp_path) -> None:
    path = tmp_path / "settings.json"

    write_settings(SavedSettings(redraw_notice_shown=True), path)

    assert json.loads(path.read_text(encoding="utf-8")) == {"redraw_notice_shown": True}


def test_the_default_path_is_under_localappdata(monkeypatch, tmp_path) -> None:
    monkeypatch.undo()  # Drop the conftest fixture's path for this test
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert settings_file.default_settings_path() == tmp_path / "ClickNick" / "settings.json"


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[true]",
        '{"redraw_on_sync": "no", "redraw_notice_shown": 1}',
        "",
    ],
    ids=["not json", "a list", "not booleans", "empty"],
)
def test_an_unreadable_file_counts_as_never_set(tmp_path, text) -> None:
    path = tmp_path / "settings.json"
    path.write_text(text, encoding="utf-8")

    assert read_settings(path) == SavedSettings()


def test_a_folder_in_place_of_the_file_counts_as_never_set(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.mkdir()

    assert read_settings(path) == SavedSettings()
    assert not write_settings(SavedSettings(redraw_on_sync=False), path)


def test_a_missing_file_counts_as_never_set(tmp_path) -> None:
    assert read_settings(tmp_path / "settings.json") == SavedSettings()


# -- AppSettings -------------------------------------------------------------------------


def test_the_setting_is_on_and_the_notice_due_on_a_new_machine(tk_root, tmp_path) -> None:
    settings = AppSettings(tmp_path / "settings.json")

    assert settings.redraw_on_sync
    assert settings.redraw_notice_due


@pytest.mark.parametrize("value", [True, False])
def test_the_setting_is_read_back_at_start(tk_root, tmp_path, value) -> None:
    path = tmp_path / "settings.json"
    write_settings(SavedSettings(redraw_on_sync=value), path)

    settings = AppSettings(path)

    assert settings.redraw_on_sync is value
    assert not settings.redraw_notice_due


def test_an_unreadable_file_starts_like_a_new_machine(tk_root, tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")

    settings = AppSettings(path)

    assert settings.redraw_on_sync
    assert settings.redraw_notice_due


def test_the_notice_and_the_setting_are_saved_together(tk_root, tmp_path) -> None:
    path = tmp_path / "settings.json"
    settings = AppSettings(path)

    settings.mark_redraw_notice_shown()
    settings.redraw_on_sync_var.set(False)

    assert read_settings(path) == SavedSettings(redraw_on_sync=False, redraw_notice_shown=True)


def test_a_failed_write_keeps_the_values_until_closing(tk_root, tmp_path, caplog) -> None:
    path = tmp_path / "settings.json"
    path.mkdir()
    settings = AppSettings(path)

    with caplog.at_level(logging.WARNING):
        settings.mark_redraw_notice_shown()

    assert not settings.redraw_notice_due
    assert "Could not save ClickNick's settings file" in caplog.text
