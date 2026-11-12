"""Tests for read_mdb_csv in clicknick.data.data_source."""

from clicknick.data.data_source import read_mdb_csv


class TestReadMdbCsv:
    def test_skips_rows_without_content(self, tmp_path):
        csv_path = tmp_path / "Address.csv"
        csv_path.write_text(
            "AddrKey,MemoryType,Address,DataType,Nickname,Use,InitialValue,Retentive,Comment\n"
            "1,X,1,0,,1,0,0,\n"
            "2,X,2,0,Input2,1,0,0,Second input\n",
            encoding="utf-8",
        )

        rows = read_mdb_csv(str(csv_path))
        assert len(rows) == 1
        only = next(iter(rows.values()))
        assert only.memory_type == "X"
        assert only.address == 2
        assert only.nickname == "Input2"
        assert only.comment == "Second input"

    def test_invalid_rows_are_ignored(self, tmp_path):
        csv_path = tmp_path / "Address.csv"
        csv_path.write_text(
            "AddrKey,MemoryType,Address,DataType,Nickname,Use,InitialValue,Retentive,Comment\n"
            "1,ZZ,1,0,BadType,1,0,0,Bad\n"
            "2,X,NotInt,0,BadAddr,1,0,0,Bad\n"
            "3,DS,1,1,Good,1,123,1,Good row\n",
            encoding="utf-8",
        )

        rows = read_mdb_csv(str(csv_path))
        assert len(rows) == 1
        row = next(iter(rows.values()))
        assert row.memory_type == "DS"
        assert row.address == 1
        assert row.initial_value == "123"

    def test_returns_addressrow_map_with_expected_fields(self, tmp_path):
        csv_path = tmp_path / "Address.csv"
        csv_path.write_text(
            "AddrKey,MemoryType,Address,DataType,Nickname,Use,InitialValue,Retentive,Comment\n"
            "100663297,DS,1,1,Temp,1,100,1,Temperature\n",
            encoding="utf-8",
        )

        rows = read_mdb_csv(str(csv_path))
        assert len(rows) == 1

        row = next(iter(rows.values()))
        assert row.memory_type == "DS"
        assert row.address == 1
        assert row.data_type == 1
        assert row.nickname == "Temp"
        assert row.comment == "Temperature"
        assert row.retentive is True

    def test_keeps_rows_with_only_an_initial_value_or_retentive(self, tmp_path):
        """The same rows the database path keeps (AddressRow.has_content)."""
        csv_path = tmp_path / "Address.csv"
        csv_path.write_text(
            "AddrKey,MemoryType,Address,DataType,Nickname,Use,InitialValue,Retentive,Comment\n"
            "100663297,DS,1,1,,0,123,0,\n"
            "100663298,DS,2,1,,0,0,1,\n"
            "100663299,DS,3,1,,1,0,0,\n",
            encoding="utf-8",
        )

        rows = read_mdb_csv(str(csv_path))

        assert sorted((r.address, r.initial_value, r.retentive) for r in rows.values()) == [
            (1, "123", False),
            (2, "0", True),
        ]

    def test_reads_clicks_address_csv(self, tmp_path):
        """CLICK writes it as UTF-8 with a BOM and CRLF, Retentive and Use as 0/1."""
        csv_path = tmp_path / "Address.csv"
        csv_path.write_bytes(
            (
                "AddrKey,MemoryType,Address,DataType,Nickname,Use,InitialValue,Retentive,Comment\r\n"
                '100663297,DS,1,1,Temp,1,100,1,"  spaced  "\r\n'
            ).encode("utf-8-sig")
        )

        row = next(iter(read_mdb_csv(str(csv_path)).values()))

        assert (row.memory_type, row.address, row.nickname) == ("DS", 1, "Temp")
        assert row.retentive is True
        assert row.comment == "  spaced  "
