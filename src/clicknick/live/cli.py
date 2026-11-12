"""``clicknick-cli`` — push commands into a running ClickNick instance.

Usage::

    clicknick-cli list                              # show active sessions
    clicknick-cli ping                              # connection state + status

    # Inspect / edit (by pyrung tag name or Click address)
    clicknick-cli get ExampleTag                    # inspect a row
    clicknick-cli set ExampleTag nickname RenamedTag # rename (staged change)
    clicknick-cli set DS1 comment "Example comment" # quoting works

    # Find free addresses
    clicknick-cli unused C                          # next free C bit -> C5
    clicknick-cli unused DS 3                        # next 3 free DS addresses
    clicknick-cli unused C100                        # next free C at or after C100
    clicknick-cli unused C1031 C1414                # one free bit near each neighbor

    # Tag annotations
    clicknick-cli tag show ExampleTag               # full tag metadata display
    clicknick-cli tag set-flag ExampleTag external  # set a boolean flag
    clicknick-cli tag set-choices Mode "Off:0" "Manual:1" "Auto:2"
    clicknick-cli tag set-range Temp_PV 0 100       # numeric range
    clicknick-cli tag set-uom Temp_PV degC          # unit of measurement
    clicknick-cli tag set-physical Clamp_FB Clamp --on-delay 50ms --off-delay 200ms
    clicknick-cli tag apply                         # edit src/plc/tags.py, then push

    # Rung commands
    clicknick-cli rung list                         # list available files
    clicknick-cli rung list main                    # rungs in main program
    clicknick-cli rung apply                        # stage all changes and open Preview Changes
    clicknick-cli rung apply main                   # stage main and open Preview Changes on it
    clicknick-cli rung apply main --select r3       # stage and show rung 3

    # Program analysis
    clicknick-cli check                             # lint the editable pyrung proposal

    # Workspace recovery
    clicknick-cli backup                            # snapshot src/plc (the last 5 are kept)
    clicknick-cli restore                           # restore the newest snapshot
    clicknick-cli restore list                      # list the older snapshots
    clicknick-cli restore 20261112-143005           # restore an older snapshot

    # Workflow
    clicknick-cli prompt-save                       # pop a save reminder in the GUI
    clicknick-cli help                              # grouped command list

    # Pick a specific session
    clicknick-cli -s MyProject get DS1

Each argument is one word, as the shell passed it. A command given as one
argument is split into words at spaces outside quotes; a backslash escapes
only ``"`` and ``\\`` inside double quotes and stays as it is elsewhere.
Commands may be chained with ``;``: at the end of an argument, as an argument
of its own, or outside quotes in that one argument::

    clicknick-cli "set C1 nickname Pump ; set C2 nickname Valve"

Sessions are identified by the .ckp project name. When exactly one session is
active, ``--session`` may be omitted.
"""

from __future__ import annotations

import argparse
import sys

from .client import send_command
from .dispatch import quote_words, split_commands
from .session import find_sessions, workspace_for_port_file


def _commands(argv: list[str], parser: argparse.ArgumentParser) -> list[list[str]]:
    """Return the words of each command in *argv*.

    One argument is a command line of its own (``"set DS1 comment 'a b'"``);
    more are the words the shell already split. Then a word ending in ``;``
    ends a command (cmd.exe passes ``Pump; set`` as ``Pump;`` and ``set``); a
    ``;`` anywhere else in a word is part of it.
    """
    if len(argv) == 1:
        try:
            return split_commands(argv[0])
        except ValueError as exc:
            parser.error(f"cannot read {argv[0]!r}: {exc}")
    commands: list[list[str]] = [[]]
    for word in argv:
        if word.endswith(";"):
            if word.rstrip(";"):
                commands[-1].append(word.rstrip(";"))
            commands.append([])
        else:
            commands[-1].append(word)
    return [words for words in commands if words]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(
        prog="clicknick-cli",
        description="Attach to a running ClickNick instance and push live edits.",
        epilog=(
            "Identifiers: use pyrung tag names (ExampleTag) or Click addresses (DS1).\n"
            "All writes land as staged changes in the address editor (Ctrl+Z to undo).\n"
            "Subcommands: tag (annotations), rung (program).\n"
            "Use 'clicknick-cli help' for a grouped command list."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--session", "-s", help="Session label (.ckp project name)")
    parser.add_argument("command", nargs="*", help="Command (chain with ';')")
    args = parser.parse_args()

    # `list` (or no args) -> show sessions
    if (not args.session and not args.command) or (args.command and args.command[0] == "list"):
        sessions = find_sessions()
        if not sessions:
            print("No active sessions")
        elif len(sessions) == 1:
            label, _, port_file = sessions[0]
            print(f"Active session: {label}")
            workspace = workspace_for_port_file(port_file)
            print(f"Project dir:    {workspace or '(building)'}")
            print("Usage: clicknick-cli <command>  (e.g. clicknick-cli get ExampleTag)")
        else:
            print("Active sessions:")
            for label, _, port_file in sessions:
                workspace = workspace_for_port_file(port_file)
                print(f"  {label}  ({workspace or 'building'})")
            print("Usage: clicknick-cli -s <session> <command>")
        return

    if not args.command:
        parser.error("no command given")

    # `help` handled locally — no server connection needed
    if args.command[0] == "help":
        from .dispatch import _format_help

        print(_format_help())
        return

    commands = [quote_words(words) for words in _commands(args.command, parser)]
    all_ok = True
    for command in commands:
        try:
            ok, text = send_command(args.session, command)
        except (FileNotFoundError, LookupError) as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        except ConnectionRefusedError:
            print("Cannot connect to session (it may have just exited)", file=sys.stderr)
            sys.exit(1)
        print(text)
        if not ok:
            all_ok = False
            break
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
