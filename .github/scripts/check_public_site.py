#!/usr/bin/env python3
# Public-site publication guard, version 1.

from __future__ import annotations

import argparse
from pathlib import Path


BLOCKED_FILENAMES = {"agents.md", "claude.md", "llms-full.txt"}


def ascii_text(value: object) -> str:
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


def blocked_reason(relative_path: Path) -> str | None:
    parts = tuple(part.lower() for part in relative_path.parts)
    if "internal" in parts:
        return "path segment named internal"
    if relative_path.name.lower() in BLOCKED_FILENAMES:
        return f"blocked filename {relative_path.name}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check generated public-site paths.")
    parser.add_argument("site", type=Path, help="Generated site directory to inspect")
    args = parser.parse_args()

    site = args.site
    if not site.is_dir():
        print(f"ERROR: public site directory does not exist: {ascii_text(site)}")
        return 2

    violations: list[tuple[Path, str]] = []
    for path in site.rglob("*"):
        relative_path = path.relative_to(site)
        if reason := blocked_reason(relative_path):
            violations.append((relative_path, reason))

    if violations:
        for relative_path, reason in sorted(violations):
            print(
                "ERROR: blocked public-site path: "
                f"{ascii_text(relative_path.as_posix())} ({reason})"
            )
        print(f"ERROR: public-site guard found {len(violations)} blocked path(s).")
        return 1

    print(f"OK: public-site guard passed: {ascii_text(site)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
