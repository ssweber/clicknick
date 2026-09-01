"""Live-session metadata keeps process discovery separate from workspace paths."""

from pathlib import Path

from clicknick.live.session import WORKSPACE_FILENAME, workspace_for_port_file


def test_workspace_metadata_is_read_beside_port_file(tmp_path: Path) -> None:
    port_file = tmp_path / "clicknick-live.port"
    port_file.write_text("12345", encoding="utf-8")
    workspace = tmp_path.parent / "Example Workspace"
    (tmp_path / WORKSPACE_FILENAME).write_text(str(workspace), encoding="utf-8")

    assert workspace_for_port_file(port_file) == workspace


def test_missing_workspace_metadata_means_building(tmp_path: Path) -> None:
    port_file = tmp_path / "clicknick-live.port"

    assert workspace_for_port_file(port_file) is None
