"""CsvDataSource reads and writes nickname CSVs in the form CLICK exports them."""

from __future__ import annotations

from pathlib import Path

import pytest
from pyclickplc.addresses import get_addr_key, parse_address

from clicknick.data.address_store import AddressStore
from clicknick.data.data_source import CsvDataSource
from clicknick.models.address_row import AddressRow

CLICK_EXPORT = Path(__file__).parent / "NicknameExport.csv"
HEADER = "Address,Data Type,Nickname,Initial Value,Retentive,Address Comment"


def _write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_bytes(text.replace("\n", "\r\n").encode(encoding))
    return path


def _export_addresses() -> list[str]:
    lines = CLICK_EXPORT.read_text(encoding="utf-8").splitlines()[1:]
    return [line.split(",", 1)[0] for line in lines]


class TestClickExport:
    def test_every_address_loads_at_its_own_key(self):
        rows = CsvDataSource(str(CLICK_EXPORT)).load_all_addresses()

        addresses = _export_addresses()
        assert [rows[get_addr_key(*parse_address(a))].display_address for a in addresses] == (
            addresses
        )
        assert len(rows) == len(addresses)
        assert rows[get_addr_key("XD", 1)].nickname == "Second Slot XD"
        assert rows[get_addr_key("XD", 16)].nickname == "Last XD"
        assert rows[get_addr_key("YD", 1)].nickname == "Second Slot YD"

    def test_saving_what_was_read_writes_clicks_file_back(self, tmp_path):
        """Same rows, same order, same quoting, and CLICK's CRLF line ends."""
        rows = CsvDataSource(str(CLICK_EXPORT)).load_all_addresses()
        out = tmp_path / "out.csv"

        assert CsvDataSource(str(out)).save_changes(list(rows.values())) == len(rows)

        expected = CLICK_EXPORT.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        assert out.read_bytes() == expected


class TestEncodingAndColumns:
    def test_a_file_saved_with_a_bom_loads(self, tmp_path):
        """Excel's "CSV UTF-8" puts a BOM before the header."""
        path = _write(
            tmp_path / "bom.csv",
            f'{HEADER}\nX001,BIT,"Start",0,No,""\nDS1,INT,"Speed",100,Yes,"rpm"\n',
            encoding="utf-8-sig",
        )

        rows = CsvDataSource(str(path)).load_all_addresses()

        assert rows[get_addr_key("X", 1)].nickname == "Start"
        assert rows[get_addr_key("DS", 1)].comment == "rpm"

    @pytest.mark.parametrize(
        "text",
        [
            "Data Type,Nickname,Initial Value,Retentive,Address Comment\nBIT,Start,0,No,\n",
            "Address,Data Type,Initial Value\nX001,BIT,0\n",
            # Excel in a locale that lists with semicolons
            "Address;Data Type;Nickname;Initial Value;Retentive;Address Comment\n"
            "X001;BIT;Start;0;No;\n",
            "",
        ],
        ids=["no Address", "no Nickname", "semicolons", "empty file"],
    )
    def test_a_file_without_address_and_nickname_columns_is_an_error(self, tmp_path, text):
        path = _write(tmp_path / "bad.csv", text)

        with pytest.raises(ValueError, match="bad.csv"):
            CsvDataSource(str(path)).load_all_addresses()

    def test_fields_name_the_columns_the_file_has(self, tmp_path):
        only_names = _write(tmp_path / "names.csv", "Address,Nickname\nX001,Start\n")
        source = CsvDataSource(str(only_names))
        source.load_all_addresses()
        assert source.fields == {"nickname"}

        full = CsvDataSource(str(CLICK_EXPORT))
        full.load_all_addresses()
        assert full.fields == {"nickname", "data_type", "initial_value", "retentive", "comment"}


class TestCsvModeStore:
    def test_a_file_not_understood_never_loads_as_an_empty_project(self, tmp_path):
        path = _write(tmp_path / "names.csv", "Name,Value\nStart,1\n")
        before = path.read_bytes()

        with pytest.raises(ValueError):
            AddressStore(CsvDataSource(str(path))).load_initial_data()

        assert path.read_bytes() == before

    def test_save_refuses_to_overwrite_a_file_a_reload_could_not_read(self, tmp_path):
        path = _write(tmp_path / "names.csv", f'{HEADER}\nX001,BIT,"Start",0,No,""\n')
        store = AddressStore(CsvDataSource(str(path)))
        store.load_initial_data()
        with store.edit_session("Rename") as session:
            session.set_field(get_addr_key("X", 2), "nickname", "Stop")

        _write(path, "Address;Nickname\nX001;Start;\nX003;Jog\n")
        before = path.read_bytes()
        assert store._on_database_update() is False
        assert store.base_state[get_addr_key("X", 1)].nickname == "Start"

        with pytest.raises(ValueError, match="names.csv"):
            store.save_all_changes()
        assert path.read_bytes() == before
        assert store.is_dirty(get_addr_key("X", 2))

        # Once the file reads again, Save goes ahead
        _write(path, f'{HEADER}\nX001,BIT,"Start",0,No,""\n')
        assert store._on_database_update() is True
        store.save_all_changes()
        assert '"Stop"' in path.read_text(encoding="utf-8")


class TestFieldValues:
    @pytest.mark.parametrize("value", ['"', ",", " ", 'a"b,c'])
    def test_a_txt_initial_value_round_trips(self, tmp_path, value):
        path = tmp_path / "txt.csv"
        rows = [
            AddressRow("TXT", 5, nickname="Sep", data_type=6, initial_value=value),
            AddressRow("TXT", 6, nickname="Next", data_type=6, comment="No"),
        ]
        CsvDataSource(str(path)).save_changes(rows)

        loaded = CsvDataSource(str(path)).load_all_addresses()

        assert loaded[get_addr_key("TXT", 5)].initial_value == value
        assert loaded[get_addr_key("TXT", 5)].comment == ""
        assert loaded[get_addr_key("TXT", 6)].comment == "No"

    def test_nickname_and_comment_are_read_as_written(self, tmp_path):
        """CLICK's database keeps them verbatim; so does the CSV."""
        path = tmp_path / "space.csv"
        comment = "  lead and trail  \r\nsecond line"
        CsvDataSource(str(path)).save_changes(
            [AddressRow("C", 1, nickname=" Motor ", comment=comment)]
        )

        row = CsvDataSource(str(path)).load_all_addresses()[get_addr_key("C", 1)]

        assert row.comment == comment
        assert row.nickname == " Motor "

    def test_lines_end_with_crlf(self, tmp_path):
        path = tmp_path / "out.csv"
        CsvDataSource(str(path)).save_changes([AddressRow("C", 1, nickname="Motor")])

        assert path.read_bytes() == (f'{HEADER}\r\nC1,BIT,"Motor",0,No,""\r\n').encode()
