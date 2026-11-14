"""Regression tests for hook.py: recorded PreToolUse payloads in, exit codes and rewrites out.

Run: timeout 120 uv run pytest devtools/mergeq -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).with_name("hook.py")
TEMP = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
REPO_FILE = str(Path(__file__).resolve().parents[2] / "src" / "clicknick" / "__init__.py")

MAIN = None
BUILDER = "bob-builder"
REVIEWER = "bob-reviewer"
READER = "bob-investigator"
MQ = "python -I devtools/mergeq/mergeq.py"


def run_hook(tool: str, value: str, agent: str | None, env: dict[str, str] | None = None):
    key = "command" if tool in ("Bash", "PowerShell") else "file_path"
    event: dict = {"tool_name": tool, "tool_input": {key: value}, "cwd": "C:/x/clicknick-wt/drum"}
    if agent:
        event.update(agent_type=agent, agent_id="a1")
    proc = subprocess.run(
        [sys.executable, "-I", str(HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
    )
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr


ALLOW, REFUSE, WRAP = "allow", "refuse", "wrap"

CASES = [
    # main session: every stage is light; bare `make` (install + lint + test) is heavy
    ("Bash", "make", MAIN, REFUSE),
    ("Bash", "make install && make", MAIN, REFUSE),
    ("Bash", "python -I devtools/mergeq/mergeq.py run --heavy --timeout 900 -- make", MAIN, ALLOW),
    ("Bash", "python -I devtools/mergeq/mergeq.py next", MAIN, ALLOW),
    ("Bash", "make lint", MAIN, ALLOW),
    ("Bash", "make lint && make test", MAIN, ALLOW),
    ("Bash", "make docs-check", MAIN, ALLOW),
    ("Bash", "make install", MAIN, ALLOW),
    ("Bash", "make install && timeout 300 uv run pytest tests/ladder -k test", MAIN, WRAP),
    ("Bash", "uv run pytest tests/ladder/test_copy.py -q", MAIN, WRAP),
    ("Bash", "git status", MAIN, ALLOW),
    ("PowerShell", "uv run pytest tests/x.py", MAIN, REFUSE),
    ("Bash", "git commit -m 'docs: run make before pytest'", MAIN, ALLOW),
    ("Bash", "cat > notes.md <<'EOF'\nthen make and pytest\nEOF", MAIN, ALLOW),
    ("Bash", "python - <<'EOF'\nprint('make test')\nEOF\nmake", MAIN, REFUSE),
    ("Edit", REPO_FILE, MAIN, ALLOW),
    # builder
    ("Bash", "make test", BUILDER, ALLOW),
    ("Bash", "make lint && make test", BUILDER, ALLOW),
    ("Bash", "make", BUILDER, REFUSE),
    ("Bash", "python -I devtools/mergeq/mergeq.py run --heavy -- make", BUILDER, REFUSE),
    ("Bash", "timeout 300 uv run pytest tests/ladder/test_copy.py -q", BUILDER, WRAP),
    ("Bash", "git commit -m 'fix(copy): x'", BUILDER, ALLOW),
    ("Write", REPO_FILE, BUILDER, ALLOW),
    # reviewer: allowlist
    ("Bash", "git -C ../clicknick-wt/drum diff dev...bob/drum", REVIEWER, ALLOW),
    ("Bash", "git log --oneline -5 | head -3", REVIEWER, ALLOW),
    ("Bash", 'grep -nE "a|b" src/clicknick/instructions/copy.py', REVIEWER, ALLOW),
    ("Bash", "rg -n foo src 2>&1 | tail -5", REVIEWER, ALLOW),
    ("Bash", "cd ../clicknick-wt/drum && git show HEAD --stat", REVIEWER, ALLOW),
    ("Bash", "timeout 300 uv run pytest tests/ladder/test_copy.py -q", REVIEWER, WRAP),
    ("Bash", "sed -n 1,40p src/clicknick/instructions/copy.py", REVIEWER, ALLOW),
    ("Write", f"{TEMP}/probe.py", REVIEWER, ALLOW),
    # reviewer: refusals
    ("Bash", "git commit -m x", REVIEWER, REFUSE),
    ("Bash", "git stash", REVIEWER, REFUSE),
    ("Bash", "git checkout -- src/x.py", REVIEWER, REFUSE),
    ("Bash", "sed -i s/a/b/ src/x.py", REVIEWER, REFUSE),
    ("Bash", "echo x > src/x.py", REVIEWER, REFUSE),
    ("Bash", "cat src/a.py >> src/b.py", REVIEWER, REFUSE),
    ("Bash", "python -c \"open('src/x.py','w')\"", REVIEWER, REFUSE),
    ("Bash", "uv run python devtools/golden.py", REVIEWER, REFUSE),
    ("Bash", "python - <<'EOF'\nprint(1)\nEOF", REVIEWER, REFUSE),
    ("Bash", "cat $(git ls-files)", REVIEWER, REFUSE),
    ("Bash", "find . -name '*.pyc' -delete", REVIEWER, REFUSE),
    ("Bash", "rm -rf build", REVIEWER, REFUSE),
    ("Bash", "make test", REVIEWER, REFUSE),
    ("Bash", "make golden", REVIEWER, REFUSE),
    ("PowerShell", "Get-Content src/x.py", REVIEWER, REFUSE),
    ("Write", REPO_FILE, REVIEWER, REFUSE),
    ("Edit", REPO_FILE, REVIEWER, REFUSE),
    # reviewer: scratch scripts run bounded (mergeq run), never bare
    ("Bash", f"{MQ} run --timeout 120 -- uv run python {TEMP}/probe.py", REVIEWER, ALLOW),
    ("Bash", f"{MQ} run --timeout 120 --name rev -- python {TEMP}/probe.py", REVIEWER, ALLOW),
    (
        "Bash",
        f"{MQ} run --timeout 120 -- python -I {TEMP}/probe.py 2>&1 | tail -5",
        REVIEWER,
        ALLOW,
    ),
    ("Bash", f"timeout 120 uv run python {TEMP}/probe.py", REVIEWER, REFUSE),
    ("Bash", f"uv run python {TEMP}/probe.py", REVIEWER, REFUSE),
    ("Bash", f"python {TEMP}/probe.py", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run -- python {TEMP}/probe.py", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 999999 -- python {TEMP}/probe.py", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 0 -- python {TEMP}/probe.py", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --heavy --timeout 60 -- python {TEMP}/probe.py", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 --env X=1 -- python {TEMP}/probe.py", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 --", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 -- python src/x.py", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 -- rm -rf build", REVIEWER, REFUSE),
    (
        "Bash",
        f"{MQ} run --timeout 60 -- bash -c 'python {TEMP}/p.py; rm -rf build'",
        REVIEWER,
        REFUSE,
    ),
    ("Bash", f"{MQ} run --timeout 60 -- node --test", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 -- python {TEMP}/p.py; rm -rf build", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 -- python {TEMP}/p.py && git commit -m x", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 -- python {TEMP}/p.py > src/x.py", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 -- python {TEMP}/p.py $(rm x)", REVIEWER, REFUSE),
    ("Bash", f"python -I {TEMP}/mergeq.py run --timeout 60 -- cat x", REVIEWER, REFUSE),
    ("Bash", f"{MQ} reap --unmanaged", REVIEWER, REFUSE),
    ("Bash", f"{MQ} run --timeout 1800 -- python {TEMP}/p.py", REVIEWER, ALLOW),
    ("Bash", f"{MQ} run --timeout 1801 -- python {TEMP}/p.py", REVIEWER, REFUSE),
    # reviewer: ruff and ty, read-only forms only
    ("Bash", "ruff check src tests", REVIEWER, ALLOW),
    ("Bash", "uv run ruff check --no-fix src", REVIEWER, ALLOW),
    ("Bash", "uv run ruff check --select F401 src 2>&1 | head -20", REVIEWER, ALLOW),
    ("Bash", "ruff format --check src", REVIEWER, ALLOW),
    ("Bash", "uv run ruff format --diff src/clicknick/instructions/copy.py", REVIEWER, ALLOW),
    ("Bash", "ruff format src --check", REVIEWER, ALLOW),
    ("Bash", "ty check src", REVIEWER, ALLOW),
    ("Bash", "uv run ty check --project . src", REVIEWER, ALLOW),
    ("Bash", "ruff check --fix src", REVIEWER, REFUSE),
    ("Bash", "ruff check src --fix", REVIEWER, REFUSE),
    ("Bash", "ruff check src --fix-only", REVIEWER, REFUSE),
    ("Bash", "uv run ruff check --unsafe-fixes src", REVIEWER, REFUSE),
    ("Bash", "ruff check --add-noqa src", REVIEWER, REFUSE),
    ("Bash", "ruff check --watch src", REVIEWER, REFUSE),
    ("Bash", "ruff check -w src", REVIEWER, REFUSE),
    ("Bash", "ruff check --config 'fix = true' src", REVIEWER, REFUSE),
    ("Bash", "ruff check --output-file src/x.txt src", REVIEWER, REFUSE),
    ("Bash", "ruff check -o src/x.txt src", REVIEWER, REFUSE),
    ("Bash", "ruff format src", REVIEWER, REFUSE),
    ("Bash", "uv run ruff format src/clicknick/instructions/copy.py", REVIEWER, REFUSE),
    ("Bash", "ruff format --check --config fix=true src", REVIEWER, REFUSE),
    ("Bash", "ruff check src; ruff format src", REVIEWER, REFUSE),
    ("Bash", "ruff check src && ruff check --fix src", REVIEWER, REFUSE),
    ("Bash", "ruff check src | tee src/out.txt", REVIEWER, REFUSE),
    ("Bash", "ruff check src > src/out.txt", REVIEWER, REFUSE),
    ("Bash", "ruff check $(git ls-files)", REVIEWER, REFUSE),
    ("Bash", "ruff --fix src", REVIEWER, REFUSE),
    ("Bash", "uv run devtools/lint.py", REVIEWER, REFUSE),
    ("Bash", "make lint", REVIEWER, REFUSE),
    ("Bash", "env", REVIEWER, ALLOW),
    # read-only agent: reads, no tests, no code
    ("Bash", "git -C ../clicknick-wt/drum diff dev...bob/drum", READER, ALLOW),
    ("Bash", 'rg -n "pytest" tests | head', READER, ALLOW),
    ("Bash", "cat devtools/mergeq/mergeq.toml", READER, ALLOW),
    ("Bash", "xxd -l 64 tests/fixtures/v4_captures/sweep_comm.bin", READER, ALLOW),
    ("Bash", "ruff check src", READER, ALLOW),
    ("Write", f"{TEMP}/notes.txt", READER, ALLOW),
    ("Bash", "uv run pytest tests/ladder/test_x.py -q", READER, REFUSE),
    ("Bash", "timeout 300 uv run pytest tests/ladder/test_x.py", READER, REFUSE),
    ("Bash", "pytest tests", READER, REFUSE),
    ("Bash", "python -m pytest tests", READER, REFUSE),
    ("Bash", "python -I -m pytest tests", READER, REFUSE),
    ("Bash", "git status && pytest tests", READER, REFUSE),
    ("Bash", "git status; uv run pytest -k x", READER, REFUSE),
    ("Bash", "make test", READER, REFUSE),
    ("Bash", "make lint", READER, REFUSE),
    ("Bash", "uv run python -m unittest", READER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 -- python {TEMP}/probe.py", READER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 -- uv run python {TEMP}/p.py", READER, REFUSE),
    ("Bash", f"{MQ} run --timeout 60 -- pytest tests", READER, REFUSE),
    ("Bash", f"python {TEMP}/probe.py", READER, REFUSE),
    ("Bash", f"uv run python {TEMP}/probe.py", READER, REFUSE),
    ("Bash", "git commit -m x", READER, REFUSE),
    ("Bash", "echo x > src/x.py", READER, REFUSE),
    ("Bash", "cat $(git ls-files)", READER, REFUSE),
    ("PowerShell", "Get-Content src/x.py", READER, REFUSE),
    ("Write", REPO_FILE, READER, REFUSE),
    ("Edit", REPO_FILE, READER, REFUSE),
    # test runs wrap, for every role
    ("Bash", "timeout 120 uv run pytest devtools/mergeq/test_mergeq.py -q", MAIN, WRAP),
    ("Bash", "timeout 120 uv run pytest devtools/mergeq/test_mergeq.py -q", REVIEWER, WRAP),
    ("Bash", "uv run --extra dev pytest x", BUILDER, WRAP),
    ("Bash", ".venv/Scripts/python -m pytest x", BUILDER, WRAP),
    ("Bash", "for f in a b; do uv run pytest $f; done", MAIN, WRAP),
    ("PowerShell", "uv run pytest tests/x.py", BUILDER, REFUSE),
    ("PowerShell", "foreach ($f in 'a','b') { uv run pytest $f }", MAIN, REFUSE),
    # comments read as comments (shlex)
    ("Bash", "# a\n# b\ngit status", REVIEWER, ALLOW),
    ("Bash", "git status\n# then the log\ngit log -1", REVIEWER, ALLOW),
    ("Bash", "git log -SOutputBlock", REVIEWER, ALLOW),
    ("Bash", "date -Iseconds", REVIEWER, ALLOW),
    ("Bash", "cat src/{a,b}.py", REVIEWER, ALLOW),
]


@pytest.mark.parametrize(("tool", "value", "agent", "want"), CASES)
def test_hook_decision(tool: str, value: str, agent: str | None, want: str) -> None:
    rc, out, err = run_hook(tool, value, agent)
    if want == REFUSE:
        assert rc == 2, f"expected refusal, got rc={rc} out={out}"
        assert err.startswith("mergeq"), err
    elif want == ALLOW:
        assert (rc, out) == (0, None), f"expected plain allow, got rc={rc} out={out} err={err}"
    else:
        assert rc == 0, err
        assert out is not None
        command = out["hookSpecificOutput"]["updatedInput"]["command"]
        assert "mergeq.py run --timeout" in command and " -- bash -c " in command
        assert "--name" in command and "@drum" in command


def test_wrap_takes_the_timeout_and_keeps_other_fields() -> None:
    event = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "timeout 5m uv run pytest -q",
            "description": "d",
            "timeout": 1000,
        },
        "cwd": "C:/w/text",
    }
    proc = subprocess.run(
        [sys.executable, "-I", str(HOOK)], input=json.dumps(event), text=True, capture_output=True
    )
    tool_input = json.loads(proc.stdout)["hookSpecificOutput"]["updatedInput"]
    assert "--timeout 300 " in tool_input["command"] and "--name main@text" in tool_input["command"]
    assert (tool_input["description"], tool_input["timeout"]) == ("d", 1000)


def test_fails_closed_on_bad_input_and_bad_config() -> None:
    proc = subprocess.run(
        [sys.executable, "-I", str(HOOK)], input="not json", text=True, capture_output=True
    )
    assert proc.returncode == 2
    missing = {"MERGEQ_CONFIG": str(Path(TEMP) / "no-such-mergeq.toml")}
    rc, _, err = run_hook("Bash", "git status", MAIN, env=missing)
    assert rc == 2 and "broken" in err
    # ...but the main session can still edit, so the hook can be repaired.
    rc, _, _ = run_hook("Edit", REPO_FILE, MAIN, env=missing)
    assert rc == 0
