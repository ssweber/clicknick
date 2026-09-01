from clicknick.views import dialogs


def test_build_system_info_includes_support_versions_and_driver(monkeypatch) -> None:
    monkeypatch.setattr(dialogs, "_installed_version", lambda _package: "0.12.0")

    info = dialogs._build_system_info("0.20.0", ["Microsoft Access Driver (*.mdb, *.accdb)"])

    assert "ClickNick: 0.20.0" in info
    assert "pyrung: 0.12.0" in info
    assert "MS Access ODBC: Microsoft Access Driver (*.mdb, *.accdb)" in info


def test_build_system_info_reports_missing_odbc_driver(monkeypatch) -> None:
    monkeypatch.setattr(dialogs, "_installed_version", lambda _package: "0.12.0")

    info = dialogs._build_system_info("0.20.0", [])

    assert "MS Access ODBC: Not installed" in info
