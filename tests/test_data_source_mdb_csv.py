"""Tests for read_mdb_csv in clicknick.data.data_source."""

import pytest

from clicknick.data.data_source import convert_mdb_csv_to_user_csv, read_mdb_csv

MDB_HEADER = "AddrKey,MemoryType,Address,DataType,Nickname,Use,InitialValue,Retentive,Comment\r\n"


class TestConvertMdbCsvToUserCsv:
    # The source is UTF-8 with a BOM because read_mdb_csv assumes it. No recording of CLICK's
    # Address.csv with a non-ASCII nickname shows that CLICK writes it so.
    def test_writes_the_copy_in_cp1252(self, tmp_path):
        source = tmp_path / "Address.csv"
        source.write_bytes((MDB_HEADER + "100663297,DS,1,1,Café,1,0,1,\r\n").encode("utf-8-sig"))
        dest = tmp_path / "copy.csv"

        convert_mdb_csv_to_user_csv(str(source), str(dest))

        assert b'"Caf\xe9"' in dest.read_bytes()

    def test_refuses_a_nickname_cp1252_lacks_and_writes_no_copy(self, tmp_path):
        source = tmp_path / "Address.csv"
        source.write_bytes((MDB_HEADER + "100663297,DS,1,1,a→b,1,0,1,\r\n").encode("utf-8-sig"))
        dest = tmp_path / "copy.csv"

        with pytest.raises(ValueError, match="DS1"):
            convert_mdb_csv_to_user_csv(str(source), str(dest))

        assert not dest.exists()


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
        """Keep a row whose only content is an initial value or Retentive.

        read_mdb_csv keeps a row only if AddressRow.has_content is True, so it drops a row that
        is only in use.
        """
        csv_path = tmp_path / "Address.csv"
        csv_path.write_text(
            "AddrKey,MemoryType,Address,DataType,Nickname,Use,InitialValue,Retentive,Comment\n"
            "33554433,C,1,0,,0,1,0,\n"
            "33554434,C,2,0,,0,0,1,\n"
            "33554435,C,3,0,,1,0,0,\n",
            encoding="utf-8",
        )

        rows = read_mdb_csv(str(csv_path))

        assert sorted((r.address, r.initial_value, r.retentive) for r in rows.values()) == [
            (1, "1", False),
            (2, "0", True),
        ]

    def test_reads_clicks_address_csv(self, tmp_path):
        """Read the Address CSV as CLICK writes it.

        CLICK writes UTF-8 with a BOM and CRLF, and writes Retentive and Use as 0 or 1.
        """
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
