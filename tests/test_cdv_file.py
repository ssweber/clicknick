"""Tests for DataView folder discovery and CDV verification."""

from pyclickplc.banks import DataType
from pyclickplc.dataview import DataViewFile

from clicknick.data.cdv_file import (
    check_cdv_files,
    click_dataview_folder,
    csv_dataview_folder,
    list_cdv_files,
)
from clicknick.utils import click_temp


class TestDataviewFolderDiscovery:
    """Tests for DataView folder discovery helpers."""

    def test_the_connected_windows_folder_not_the_first_click_folder(self, monkeypatch, tmp_path):
        """Another window's folder, or one a crash left, sorts first: it is never taken."""
        monkeypatch.setattr(click_temp, "_windows_temp_path", lambda: str(tmp_path))
        other = tmp_path / "CLICK (0001A2B4)" / "DataView"
        connected = tmp_path / "CLICK (00C40F12)" / "DataView"
        other.mkdir(parents=True)
        connected.mkdir(parents=True)

        assert click_dataview_folder(0x00C40F12) == connected

    def test_a_window_without_a_dataview_folder_has_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(click_temp, "_windows_temp_path", lambda: str(tmp_path))
        (tmp_path / "CLICK (0001A2B4)" / "DataView").mkdir(parents=True)
        (tmp_path / "CLICK (00C40F12)").mkdir()

        assert click_dataview_folder(0x00C40F12) is None

    def test_a_csv_folder_is_its_own_unless_it_is_a_click_temp_folder(self, monkeypatch, tmp_path):
        temp = tmp_path / "temp"
        own = tmp_path / "projects"
        (temp / "CLICK (00C40F12)").mkdir(parents=True)
        own.mkdir()
        monkeypatch.setattr(click_temp, "_windows_temp_path", lambda: str(temp))

        assert csv_dataview_folder(own / "a.csv") == own
        assert csv_dataview_folder(temp / "CLICK (00C40F12)" / "Address.csv") is None
        assert csv_dataview_folder(tmp_path / "gone" / "a.csv") is None

    def test_list_cdv_files_sorted_and_filtered(self, tmp_path):
        folder = tmp_path / "DataView"
        folder.mkdir()

        (folder / "zeta.cdv").write_text("", encoding="utf-8")
        (folder / "Alpha.cdv").write_text("", encoding="utf-8")
        (folder / "notes.txt").write_text("", encoding="utf-8")

        files = list_cdv_files(folder)
        assert [f.name for f in files] == ["Alpha.cdv", "zeta.cdv"]

    def test_check_cdv_files_counts_and_aggregation(self, tmp_path):
        dataview_dir = tmp_path / "DataView"
        dataview_dir.mkdir()

        ok = DataViewFile()
        ok.rows[0].address = "X001"
        ok.rows[0].data_type = DataType.BIT
        ok.save(dataview_dir / "ok.cdv")

        bad = DataViewFile()
        bad.rows[0].address = "DS1"
        bad.rows[0].data_type = DataType.BIT
        bad.save(dataview_dir / "bad.cdv")

        issues, checked = check_cdv_files(dataview_dir)
        assert checked == 2
        assert len(issues) == 1
        assert "Data type mismatch" in issues[0]

    def test_check_cdv_files_without_a_folder(self):
        issues, checked = check_cdv_files(None)
        assert checked == 0
        assert issues == []
