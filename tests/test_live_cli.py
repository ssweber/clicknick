"""``clicknick-cli`` sends each argument to the app as the word the shell passed."""

from __future__ import annotations

import sys

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.live import cli
from clicknick.live.dispatch import DispatchContext, dispatch


class MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def load_all_addresses(self):
        return {}

    def save_changes(self, rows):
        return len(rows)


@pytest.fixture
def store():
    s = AddressStore(MockDataSource())
    s.load_initial_data()
    return s


def _run(monkeypatch, store, *argv: str) -> list[str]:
    """Run clicknick-cli with *argv* against *store*; return the commands it sent."""
    sent: list[str] = []

    def _send(_label, command):
        sent.append(command)
        try:
            return True, dispatch(DispatchContext(store=store), command)
        except ValueError as exc:
            return False, str(exc)

    monkeypatch.setattr(cli, "send_command", _send)
    monkeypatch.setattr(sys, "argv", ["clicknick-cli", *argv])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 0
    return sent


def _comment(store, display: str) -> str:
    mem, addr = display.rstrip("0123456789"), int(display.lstrip("CDS"))
    return store.get_visible_row(get_addr_key(mem, addr)).comment


@pytest.mark.parametrize(
    "comment",
    [
        "Don't start",
        'Valve "B" open',
        "Pump 'A'  run",
        r"Path C:\temp\new",
        "Fill; then drain",
        "Pump #2",
    ],
)
def test_an_argument_reaches_the_store_as_typed(monkeypatch, store, comment):
    sent = _run(monkeypatch, store, "set", "DS1", "comment", comment)

    assert len(sent) == 1
    assert _comment(store, "DS1") == comment


def test_an_empty_argument_clears_the_field(monkeypatch, store):
    _run(monkeypatch, store, "set", "DS1", "comment", "Old")
    _run(monkeypatch, store, "set", "DS1", "comment", "")

    assert _comment(store, "DS1") == ""


def test_words_without_quotes_are_joined_into_the_value(monkeypatch, store):
    _run(monkeypatch, store, "set", "DS1", "comment", "Main", "motor", "run")

    assert _comment(store, "DS1") == "Main motor run"


def test_a_semicolon_argument_chains_commands(monkeypatch, store):
    sent = _run(
        monkeypatch, store, "set", "C1", "comment", "Pump", ";", "set", "C2", "comment", "Valve"
    )

    assert len(sent) == 2
    assert (_comment(store, "C1"), _comment(store, "C2")) == ("Pump", "Valve")


def test_one_argument_is_a_command_line_chained_at_semicolons(monkeypatch, store):
    sent = _run(monkeypatch, store, "set C1 comment Pump ; set C2 comment 'Valve; spare'")

    assert len(sent) == 2
    assert (_comment(store, "C1"), _comment(store, "C2")) == ("Pump", "Valve; spare")


def test_a_word_ending_in_a_semicolon_ends_the_command(monkeypatch, store):
    # cmd.exe: clicknick-cli set C1 comment Pump; set C2 comment Valve
    sent = _run(
        monkeypatch, store, "set", "C1", "comment", "Pump;", "set", "C2", "comment", "Valve"
    )

    assert len(sent) == 2
    assert (_comment(store, "C1"), _comment(store, "C2")) == ("Pump", "Valve")


@pytest.mark.parametrize(
    ("command", "comment"),
    [
        (r"set DS1 comment C:\temp\new", r"C:\temp\new"),
        (r"set DS1 comment 'C:\temp\new'", r"C:\temp\new"),
        (r'set DS1 comment "C:\temp"', r"C:\temp"),
        (r'set DS1 comment "C:\\temp"', r"C:\temp"),
        (r'set DS1 comment "Valve \"B\" open"', 'Valve "B" open'),
    ],
)
def test_one_argument_escapes_only_quote_and_backslash_in_double_quotes(
    monkeypatch, store, command, comment
):
    _run(monkeypatch, store, command)

    assert _comment(store, "DS1") == comment


def test_an_unclosed_quote_sends_nothing(monkeypatch, store, capsys):
    sent: list[str] = []
    monkeypatch.setattr(cli, "send_command", lambda _label, command: sent.append(command))
    monkeypatch.setattr(sys, "argv", ["clicknick-cli", "set DS1 comment 'Don"])

    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 2
    assert sent == []
    assert "No closing quotation" in capsys.readouterr().err
