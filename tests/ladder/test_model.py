"""Tests for clicknick.ladder.model — Contact, Coil, RungGrid parsing."""

import pytest

from clicknick.ladder.model import Coil, Contact, InstructionType, RungGrid


class TestContact:
    def test_from_csv_token_no(self):
        c = Contact.from_csv_token("X001")
        assert c.type == InstructionType.CONTACT_NO
        assert c.operand == "X001"
        assert c.immediate is False

    def test_from_csv_token_nc(self):
        c = Contact.from_csv_token("~X003")
        assert c.type == InstructionType.CONTACT_NC
        assert c.operand == "X003"
        assert c.immediate is False

    def test_from_csv_token_no_immediate(self):
        c = Contact.from_csv_token("X001.immediate")
        assert c.type == InstructionType.CONTACT_NO
        assert c.operand == "X001"
        assert c.immediate is True

    def test_from_csv_token_nc_immediate(self):
        c = Contact.from_csv_token("~X003.immediate")
        assert c.type == InstructionType.CONTACT_NC
        assert c.operand == "X003"
        assert c.immediate is True

    def test_from_csv_invalid_operand(self):
        with pytest.raises(ValueError, match="Invalid operand"):
            Contact.from_csv_token("XABC")

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

    def test_func_code_no_immediate(self):
        c = Contact(InstructionType.CONTACT_NO, "X001", immediate=True)
        assert c.func_code == "4099"

    def test_func_code_nc_immediate(self):
        c = Contact(InstructionType.CONTACT_NC, "X001", immediate=True)
        assert c.func_code == "4100"

    def test_to_csv_immediate(self):
        c = Contact(InstructionType.CONTACT_NO, "X001", immediate=True)
        assert c.to_csv() == "X001.immediate"


class TestCoil:
    def test_from_csv_token_out(self):
        c = Coil.from_csv_token("out(Y001)")
        assert c.type == InstructionType.COIL_OUT
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is False

    def test_from_csv_token_latch(self):
        c = Coil.from_csv_token("latch(Y001)")
        assert c.type == InstructionType.COIL_LATCH
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is False

    def test_from_csv_token_reset(self):
        c = Coil.from_csv_token("reset(Y001)")
        assert c.type == InstructionType.COIL_RESET
        assert c.operand == "Y001"
        assert c.range_end is None
        assert c.immediate is False

    def test_from_csv_token_immediate_outer_rejected(self):
        with pytest.raises(ValueError, match="inner wrapper"):
            Coil.from_csv_token("immediate(out(Y1))")

    def test_from_csv_token_immediate_inner(self):
        c = Coil.from_csv_token("out(immediate(Y1))")
        assert c.type == InstructionType.COIL_OUT
        assert c.operand == "Y1"
        assert c.range_end is None
        assert c.immediate is True

    def test_from_csv_token_range(self):
        c = Coil.from_csv_token("out(Y1..Y2)")
        assert c.type == InstructionType.COIL_OUT
        assert c.operand == "Y1"
        assert c.range_end == "Y2"
        assert c.immediate is False

    def test_from_csv_token_range_immediate_outer_rejected(self):
        with pytest.raises(ValueError, match="inner wrapper"):
            Coil.from_csv_token("immediate(out(Y1..Y2))")

    def test_from_csv_token_range_immediate_inner(self):
        c = Coil.from_csv_token("out(immediate(Y1..Y2))")
        assert c.type == InstructionType.COIL_OUT
        assert c.operand == "Y1"
        assert c.range_end == "Y2"
        assert c.immediate is True

    def test_from_csv_token_invalid(self):
        with pytest.raises(ValueError, match="Cannot parse coil"):
            Coil.from_csv_token("Y001")

    def test_from_csv_token_invalid_range_delimiter(self):
        with pytest.raises(ValueError, match="unsupported"):
            Coil.from_csv_token("out(Y1:Y2)")

    def test_from_csv_token_invalid_operand(self):
        with pytest.raises(ValueError, match="Invalid operand"):
            Coil.from_csv_token("out(YABC)")

    def test_to_csv(self):
        c = Coil(InstructionType.COIL_OUT, "Y001")
        assert c.to_csv() == "out(Y001)"

    def test_to_csv_immediate_canonical_inner_wrapper(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", immediate=True)
        assert c.to_csv() == "out(immediate(Y1))"

    def test_to_csv_range(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", range_end="Y2")
        assert c.to_csv() == "out(Y1..Y2)"

    def test_to_csv_range_immediate(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", range_end="Y2", immediate=True)
        assert c.to_csv() == "out(immediate(Y1..Y2))"

    def test_func_code_out(self):
        c = Coil(InstructionType.COIL_OUT, "Y001")
        assert c.func_code == "8193"

    def test_func_code_out_immediate(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", immediate=True)
        assert c.func_code == "8197"

    def test_func_code_out_range(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", range_end="Y2")
        assert c.func_code == "8207"

    def test_func_code_out_range_immediate(self):
        c = Coil(InstructionType.COIL_OUT, "Y1", range_end="Y2", immediate=True)
        assert c.func_code == "8208"

    def test_func_code_latch_reset(self):
        assert Coil(InstructionType.COIL_LATCH, "Y1").func_code == "8195"
        assert Coil(InstructionType.COIL_RESET, "Y1").func_code == "8196"


class TestRungGrid:
    def test_from_csv_basic(self):
        g = RungGrid.from_csv("X001,->,:out(Y001)")
        assert g.contact.type == InstructionType.CONTACT_NO
        assert g.contact.operand == "X001"
        assert g.series_contacts == []
        assert g.coil.operand == "Y001"

    def test_from_csv_nc(self):
        g = RungGrid.from_csv("~X003,->,:out(Y002)")
        assert g.contact.type == InstructionType.CONTACT_NC
        assert g.contact.operand == "X003"
        assert g.series_contacts == []
        assert g.coil.operand == "Y002"

    def test_from_csv_two_series_contacts(self):
        g = RungGrid.from_csv("X001,X002,->,:out(Y001)")
        assert [c.to_csv() for c in g.contacts] == ["X001", "X002"]
        assert g.coil.to_csv() == "out(Y001)"

    def test_to_csv_two_series_contacts(self):
        g = RungGrid.from_csv("X001,~X002,->,:out(Y001)")
        assert g.to_csv() == "X001,~X002,->,:out(Y001)"

    def test_from_csv_no_coil(self):
        with pytest.raises(ValueError, match="No coil found"):
            RungGrid.from_csv("X001,->")

    def test_to_csv(self):
        g = RungGrid.from_csv("X001,->,:out(Y001)")
        assert g.to_csv() == "X001,->,:out(Y001)"

    def test_to_csv_contact_immediate(self):
        g = RungGrid.from_csv("X001.immediate,->,:out(Y001)")
        assert g.to_csv() == "X001.immediate,->,:out(Y001)"

    def test_reject_outer_immediate_wrapper_in_rung_csv(self):
        with pytest.raises(ValueError, match="inner wrapper"):
            RungGrid.from_csv("X001,->,:immediate(out(Y1))")

    def test_to_csv_coil_range(self):
        g = RungGrid.from_csv("X001,->,:out(Y1..Y2)")
        assert g.to_csv() == "X001,->,:out(Y1..Y2)"

    def test_csv_round_trips(self):
        cases = [
            "X001,->,:out(Y001)",
            "~X003,->,:out(Y002)",
            "X010,->,:out(Y100)",
            "X1.immediate,->,:out(immediate(Y1))",
            "~X3.immediate,->,:latch(immediate(Y1..Y2))",
            "X001,->,:reset(Y1..Y2)",
        ]
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
