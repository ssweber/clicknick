"""``clicknick-live`` — push commands into a running ClickNick instance.

Usage::

    clicknick-live list                              # show active sessions
    clicknick-live ping                              # liveness check

    # Inspect / edit (by pyrung tag name or Click address)
    clicknick-live get Motor_Run                     # inspect a row
    clicknick-live set Motor_Run nickname MotorRun   # rename (unsaved change)
    clicknick-live set DS1 comment "Main motor"      # quoting works

    # Tag annotations
    clicknick-live tag show Motor_Run                # full tag metadata display
    clicknick-live tag set-flag Motor_Run external   # set a boolean flag
    clicknick-live tag set-choices Mode "Off:0" "Manual:1" "Auto:2"
    clicknick-live tag set-range Temp_PV 0 100       # numeric range
    clicknick-live tag set-uom Temp_PV degC          # unit of measurement
    clicknick-live tag set-physical Clamp_FB Clamp --on-delay 50ms --off-delay 200ms

    # Rung commands
    clicknick-live rung list                         # list available files
    clicknick-live rung list main                    # rungs in main program
    clicknick-live rung preview main --select r3     # diff for rung 3
    clicknick-live rung preview main                 # full program diff
    clicknick-live rung apply main                   # pyrung -> ladder CSVs

    # DAP simulation
    clicknick-live dap start                         # launch pyrung DAP subprocess
    clicknick-live dap status                        # check simulation state
    clicknick-live dap stop                          # terminate

    # Pick a specific session
    clicknick-live -s MyProject get DS1

Commands may be chained with ``;``::

    clicknick-live "set C1 nickname Pump ; set C2 nickname Valve"

Sessions are identified by the .ckp project name. When exactly one session is
active, ``--session`` may be omitted.
"""

from __future__ import annotations

import argparse
import sys

from .client import send_command
from .session import list_sessions


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(
        prog="clicknick-live",
        description="Attach to a running ClickNick instance and push live edits.",
        epilog=(
            "Identifiers: use pyrung tag names (Motor_Run) or Click addresses (DS1).\n"
            "All writes land as unsaved changes in the address editor (Ctrl+Z to undo).\n"
            "Subcommands: tag (annotations), rung (program), dap (simulation)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--session", "-s", help="Session label (.ckp project name)")
    parser.add_argument("command", nargs="*", help="Command (chain with ';')")
    args = parser.parse_args()

    # `list` (or no args) -> show sessions
    if (not args.session and not args.command) or (args.command and args.command[0] == "list"):
        sessions = list_sessions()
        if not sessions:
            print("No active sessions")
        elif len(sessions) == 1:
            print(f"Active session: {sessions[0]}")
            print("Usage: clicknick-live <command>  (e.g. clicknick-live get Motor_Run)")
        else:
            print("Active sessions:")
            for name in sessions:
                print(f"  {name}")
            print("Usage: clicknick-live -s <session> <command>")
        return

    if not args.command:
        parser.error("no command given")

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
