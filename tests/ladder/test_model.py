"""Tests for clicknick.ladder.model — Contact, Coil, RungGrid parsing."""

import pytest

from clicknick.ladder.model import Coil, Contact, InstructionType, RungGrid


class TestContact:
    def test_from_csv_token_no(self):
        c = Contact.from_csv_token("X001")
        assert c.type == InstructionType.CONTACT_NO
        assert c.operand == "X001"

    def test_from_csv_token_nc(self):
        c = Contact.from_csv_token("~X003")
        assert c.type == InstructionType.CONTACT_NC
        assert c.operand == "X003"

    def test_to_csv_no(self):
        c = Contact(InstructionType.CONTACT_NO, "X001")
        assert c.to_csv() == "X001"

    def test_to_csv_nc(self):
        c = Contact(InstructionType.CONTACT_NC, "X003")
        assert c.to_csv() == "~X003"

    def test_func_code_no(self):
        c = Contact(InstructionType.CONTACT_NO, "X001")
        assert c.func_code == "4097"

    def test_func_code_nc(self):
        c = Contact(InstructionType.CONTACT_NC, "X001")
        assert c.func_code == "4098"


class TestCoil:
    def test_from_csv_token_out(self):
        c = Coil.from_csv_token("out(Y001)")
        assert c.type == InstructionType.COIL_OUT
        assert c.operand == "Y001"

    def test_from_csv_token_invalid(self):
        with pytest.raises(ValueError, match="Cannot parse coil"):
            Coil.from_csv_token("Y001")

    def test_from_csv_token_unsupported_latch(self):
        with pytest.raises(ValueError, match="Unsupported coil type"):
            Coil.from_csv_token("latch(Y001)")

    def test_to_csv(self):
        c = Coil(InstructionType.COIL_OUT, "Y001")
        assert c.to_csv() == "out(Y001)"

    def test_func_code(self):
        c = Coil(InstructionType.COIL_OUT, "Y001")
        assert c.func_code == "8193"


class TestRungGrid:
    def test_from_csv_basic(self):
        g = RungGrid.from_csv("X001,->,:out(Y001)")
        assert g.contact.type == InstructionType.CONTACT_NO
        assert g.contact.operand == "X001"
        assert g.coil.operand == "Y001"

    def test_from_csv_nc(self):
        g = RungGrid.from_csv("~X003,->,:out(Y002)")
        assert g.contact.type == InstructionType.CONTACT_NC
        assert g.contact.operand == "X003"
        assert g.coil.operand == "Y002"

    def test_from_csv_no_coil(self):
        with pytest.raises(ValueError, match="No coil found"):
            RungGrid.from_csv("X001,->")

    def test_to_csv(self):
        g = RungGrid.from_csv("X001,->,:out(Y001)")
        assert g.to_csv() == "X001,->,:out(Y001)"

    def test_csv_round_trips(self):
        cases = ["X001,->,:out(Y001)", "~X003,->,:out(Y002)", "X010,->,:out(Y100)"]
        for csv in cases:
            g = RungGrid.from_csv(csv)
            assert g.to_csv() == csv

    def test_repr(self):
        g = RungGrid.from_csv("X001,->,:out(Y001)")
        assert "X001" in repr(g)
        assert "out(Y001)" in repr(g)

    def test_repr_with_nickname(self):
        g = RungGrid.from_csv("X001,->,:out(Y001)")
        g.nickname = "Start"
        assert "Start" in repr(g)
