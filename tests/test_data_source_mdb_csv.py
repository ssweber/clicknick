"""Tests for read_mdb_csv in clicknick.data.data_source."""

from clicknick.data.data_source import read_mdb_csv


class TestReadMdbCsv:
    def test_skips_empty_nickname_and_comment(self, tmp_path):
        csv_path = tmp_path / "Address.csv"
        csv_path.write_text(
            "AddrKey,MemoryType,Address,DataType,Nickname,Use,InitialValue,Retentive,Comment\n"
            "1,X,1,0,,,1,0,\n"
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
