"""Tests for ClickNick CDV file helper wrappers."""

from clicknick.models.dataview_row import DataType, create_empty_dataview
from clicknick.views.dataview_editor.cdv_file import (
    check_cdv_files,
    get_dataview_folder,
    list_cdv_files,
    save_cdv,
)


class TestDataviewFolderDiscovery:
    """Tests for DataView folder discovery helpers."""

    def test_get_dataview_folder_invalid_path(self, tmp_path):
        assert get_dataview_folder(tmp_path / "missing") is None

    def test_get_dataview_folder_found(self, tmp_path):
        project = tmp_path / "ProjectA"
        dataview = project / "CLICK (00010A98)" / "DataView"
        dataview.mkdir(parents=True)

        found = get_dataview_folder(project)
        assert found == dataview

    def test_list_cdv_files_sorted_and_filtered(self, tmp_path):
        folder = tmp_path / "DataView"
        folder.mkdir()

        (folder / "zeta.cdv").write_text("", encoding="utf-8")
        (folder / "Alpha.cdv").write_text("", encoding="utf-8")
        (folder / "notes.txt").write_text("", encoding="utf-8")

        files = list_cdv_files(folder)
        assert [f.name for f in files] == ["Alpha.cdv", "zeta.cdv"]

    def test_check_cdv_files_counts_and_aggregation(self, tmp_path):
        project = tmp_path / "MyProject"
        dataview_dir = project / "CLICK (00010A98)" / "DataView"
        dataview_dir.mkdir(parents=True)

        rows_ok = create_empty_dataview()
        rows_ok[0].address = "X001"
        rows_ok[0].data_type = DataType.BIT
        save_cdv(dataview_dir / "ok.cdv", rows_ok, has_new_values=False)

        rows_bad = create_empty_dataview()
        rows_bad[0].address = "DS1"
        rows_bad[0].data_type = DataType.BIT
        save_cdv(dataview_dir / "bad.cdv", rows_bad, has_new_values=False)

        issues, checked = check_cdv_files(project)
        assert checked == 2
        assert len(issues) == 1
        assert "Data type mismatch" in issues[0]

    def test_check_cdv_files_missing_folder(self, tmp_path):
        issues, checked = check_cdv_files(tmp_path / "NoProject")
        assert checked == 0
        assert issues == []
