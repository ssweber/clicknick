"""Wizard terminal UI for ladder capture workflow."""

from __future__ import annotations

from clicknick.ladder.capture_workflow import run_tui


def main() -> int:
    return run_tui()


if __name__ == "__main__":
    raise SystemExit(main())
