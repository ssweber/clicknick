"""``clicknick-cli`` — push commands into a running ClickNick instance.

Usage::

    clicknick-cli list                              # show active sessions
    clicknick-cli ping                              # connection state + status

    # Inspect / edit (by pyrung tag name or Click address)
    clicknick-cli get Motor_Run                     # inspect a row
    clicknick-cli set Motor_Run nickname MotorRun   # rename (unsaved change)
    clicknick-cli set DS1 comment "Main motor"      # quoting works

    # Find free addresses (alias: free)
    clicknick-cli unused C                          # next free C bit -> C5
    clicknick-cli unused DS 3                        # next 3 free DS addresses
    clicknick-cli unused C100                        # next free C at or after C100
    clicknick-cli unused C1031 C1414                # one free bit near each neighbor

    # Tag annotations
    clicknick-cli tag show Motor_Run                # full tag metadata display
    clicknick-cli tag set-flag Motor_Run external   # set a boolean flag
    clicknick-cli tag set-choices Mode "Off:0" "Manual:1" "Auto:2"
    clicknick-cli tag set-range Temp_PV 0 100       # numeric range
    clicknick-cli tag set-uom Temp_PV degC          # unit of measurement
    clicknick-cli tag set-physical Clamp_FB Clamp --on-delay 50ms --off-delay 200ms

    # Rung commands
    clicknick-cli rung list                         # list available files
    clicknick-cli rung list main                    # rungs in main program
    clicknick-cli rung preview                      # scan all files for changes
    clicknick-cli rung preview main                 # full program diff
    clicknick-cli rung preview main --select r3     # diff for rung 3
    clicknick-cli rung apply main                   # pyrung -> ladder CSVs

    # DAP simulation
    clicknick-cli dap start                         # launch pyrung DAP subprocess
    clicknick-cli dap status                        # check simulation state
    clicknick-cli dap stop                          # terminate

    # Pick a specific session
    clicknick-cli -s MyProject get DS1

Commands may be chained with ``;``::

    clicknick-cli "set C1 nickname Pump ; set C2 nickname Valve"

Sessions are identified by the .ckp project name. When exactly one session is
active, ``--session`` may be omitted.
"""

from __future__ import annotations

import argparse
import sys

from .client import send_command
from .session import find_sessions


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(
        prog="clicknick-cli",
        description="Attach to a running ClickNick instance and push live edits.",
        epilog=(
            "Identifiers: use pyrung tag names (Motor_Run) or Click addresses (DS1).\n"
            "All writes land as unsaved changes in the address editor (Ctrl+Z to undo).\n"
            "Subcommands: tag (annotations), rung (program), dap (simulation).\n"
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
            print(f"Project dir:    {port_file.parent / 'pyrung_project'}")
            print("Usage: clicknick-cli <command>  (e.g. clicknick-cli get Motor_Run)")
        else:
            print("Active sessions:")
            for label, _, port_file in sessions:
                print(f"  {label}  ({port_file.parent / 'pyrung_project'})")
            print("Usage: clicknick-cli -s <session> <command>")
        return

    if not args.command:
        parser.error("no command given")

    # `help` handled locally — no server connection needed
    if args.command[0] == "help":
        from .dispatch import _format_help

        print(_format_help())
        return

    raw = " ".join(args.command)
    commands = [c.strip() for c in raw.split(";") if c.strip()]
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
