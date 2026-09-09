"""Release report mirroring can refresh a directory containing latest aliases."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def test_report_index_can_be_refreshed_with_latest_aliases(tmp_path):
    script = Path(__file__).resolve().parents[1] / ".github/scripts/collect_trust_reports.py"
    spec = importlib.util.spec_from_file_location("collect_trust_reports", script)
    assert spec is not None and spec.loader is not None
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)

    for version in ("0.9.0", "0.23.0"):
        (tmp_path / f"clicknick-trust-report-{version}.html").write_text(version)
        (tmp_path / f"clicknick-sbom-{version}.cyclonedx.json").write_text(version)

    assert collector.write_index(tmp_path) == 2
    assert collector.write_index(tmp_path) == 2
    assert (tmp_path / "clicknick-trust-report-latest.html").read_text() == "0.23.0"
    assert (tmp_path / "clicknick-sbom-latest.cyclonedx.json").read_text() == "0.23.0"
    index = (tmp_path / "reports.md").read_text()
    assert index.index("| 0.23.0 |") < index.index("| 0.9.0 |")
    assert "| latest |" not in index
