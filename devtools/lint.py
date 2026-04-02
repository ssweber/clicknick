import argparse
import subprocess
import sys

# Update as needed.
SRC_PATHS = ["src", "tests", "devtools"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lint checks for the repository.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run read-only checks suitable for CI (no autofix).",
    )
    return parser.parse_args()


def run(cmd: list[str]) -> int:
    print()
    print(f"==> {' '.join(cmd)}")
    try:
        subprocess.run(cmd, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"Error: {exc}")
        return 1
    except FileNotFoundError as exc:
        print(f"Executable not found: {exc}")
        return 1

    return 0


def main() -> int:
    args = parse_args()
    print()

    errcount = 0
    if args.check:
        errcount += run(["ssort", "--check", *SRC_PATHS])
    else:
        errcount += run(["ssort", *SRC_PATHS])

    if args.check:
        errcount += run(["ruff", "check", *SRC_PATHS])
    else:
        errcount += run(["ruff", "check", "--fix", *SRC_PATHS])

    if args.check:
        errcount += run(["ruff", "format", "--check", *SRC_PATHS])
    else:
        errcount += run(["ruff", "format", *SRC_PATHS])

    # errcount += run(["basedpyright", *SRC_PATHS])

    print()

    if errcount != 0:
        print(f"Lint failed with {errcount} error(s).")
    else:
        print("Lint passed.")
    print()

    return errcount


if __name__ == "__main__":
    sys.exit(main())
