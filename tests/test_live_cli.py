"""``clicknick-cli`` sends each argument to the app as the word the shell passed."""

from __future__ import annotations

import shlex
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


# Each example of the module docstring, as typed, and the command it sends.
_EXAMPLES = {
    "ping": "ping",
    "get ExampleTag": "get ExampleTag",
    "set ExampleTag nickname RenamedTag": "set ExampleTag nickname RenamedTag",
    'set DS1 comment "Example comment"': "set DS1 comment 'Example comment'",
    "unused C": "unused C",
    "unused DS 3": "unused DS 3",
    "unused C100": "unused C100",
    "unused C1031 C1414": "unused C1031 C1414",
    "tag show ExampleTag": "tag show ExampleTag",
    "tag set-flag ExampleTag external": "tag set-flag ExampleTag external",
    'tag set-choices Mode "Off:0" "Manual:1" "Auto:2"': "tag set-choices Mode Off:0 Manual:1 Auto:2",
    "tag set-range Temp_PV 0 100": "tag set-range Temp_PV 0 100",
    "tag set-uom Temp_PV degC": "tag set-uom Temp_PV degC",
    "tag set-physical Clamp_FB Clamp --on-delay 50ms --off-delay 200ms": (
        "tag set-physical Clamp_FB Clamp --on-delay 50ms --off-delay 200ms"
    ),
    "tag apply": "tag apply",
    "rung list": "rung list",
    "rung list main": "rung list main",
    "rung apply": "rung apply",
    "rung apply main": "rung apply main",
    "rung apply main --select r3": "rung apply main --select r3",
    "check": "check",
    "backup": "backup",
    "restore": "restore",
    "restore list": "restore list",
    "restore 20261112T193005Z": "restore 20261112T193005Z",
    "prompt-save": "prompt-save",
}


def _main(monkeypatch, *argv: str) -> list[tuple[str | None, str]]:
    sent: list[tuple[str | None, str]] = []
    monkeypatch.setattr(
        cli, "send_command", lambda label, text: (sent.append((label, text)), (True, ""))[1]
    )
    monkeypatch.setattr(sys, "argv", ["clicknick-cli", *argv])
    with pytest.raises(SystemExit):
        cli.main()
    return sent


def test_the_table_holds_every_documented_example():
    documented = {
        line.strip().removeprefix("clicknick-cli ").split(" #")[0].strip()
        for line in cli.__doc__.splitlines()
        if line.strip().startswith("clicknick-cli ")
    }
    local = {
        "list",
        "help",
        "-s MyProject get DS1",
        '"set C1 nickname Pump ; set C2 nickname Valve"',
    }
    assert documented - local == set(_EXAMPLES)


@pytest.mark.parametrize(("line", "expected"), _EXAMPLES.items())
def test_every_documented_example_is_sent_as_written(monkeypatch, line, expected):
    assert _main(monkeypatch, *shlex.split(line)) == [(None, expected)]


@pytest.mark.parametrize(
    ("argv", "label", "expected"),
    [
        (["rung", "apply", "main", "--select", "r3,r7"], None, "rung apply main --select r3,r7"),
        (
            ["tag", "set-physical", "Clamp_FB", "Clamp", "--system", "S"],
            None,
            "tag set-physical Clamp_FB Clamp --system S",
        ),
        (
            ["--session", "MyProject", "rung", "apply", "--select", "r3"],
            "MyProject",
            "rung apply --select r3",
        ),
        (["-s", "MyProject", "get", "DS1"], "MyProject", "get DS1"),
        (["get", "-h"], None, "get -h"),
    ],
)
def test_an_option_given_as_its_own_word_is_part_of_the_command(monkeypatch, argv, label, expected):
    assert _main(monkeypatch, *argv) == [(label, expected)]


@pytest.mark.parametrize(
    "argv",
    [
        ["set", "DS1", "comment", "x", "-s", "MyProject"],
        ["get", "DS1", "--session", "MyProject"],
        ["set", "C1", "comment", "a", ";", "get", "C1", "-s", "MyProject"],
    ],
)
def test_a_session_option_after_the_command_is_refused(monkeypatch, capsys, argv):
    sent: list[str] = []
    monkeypatch.setattr(cli, "send_command", lambda label, text: (sent.append(text), (True, ""))[1])
    monkeypatch.setattr(sys, "argv", ["clicknick-cli", *argv])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 2
    assert sent == []
    assert "put -s/--session before the command" in capsys.readouterr().err
