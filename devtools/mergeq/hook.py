"""PreToolUse hook for mergeq: heavy suites stay in the queue, test runs stay timed and
killable, and the reviewer agent stays read-only.

Wired once in .claude/settings.json for Bash, PowerShell, Write, Edit and NotebookEdit.
Reads the hook JSON on stdin. Exit 2 + stderr refuses the call (the reason goes back to the
model); exit 0 allows it, optionally with JSON on stdout that rewrites the command.

It fails CLOSED: if the hook itself breaks (bad JSON, bad mergeq.toml), shell calls are
refused with the error, so enforcement can't silently lapse. File edits by anyone but the
reviewer are never checked, so the Edit tool can always repair hook.py or mergeq.toml.

Rules (mergeq.toml [hook]):
- heavy: every non-light [stages] command plus heavy_extra. Refused for subagents; the main
  session must run it through `mergeq.py run --heavy` or the queue. heavy_exempt takes
  a main-session command back out, for one whose work happens off this machine.
- needs_timeout (e.g. pytest): a Bash command is rewritten to run under
  `mergeq.py run --timeout N --name <agent>@<worktree> -- bash -c '<command>'`, so it gets a
  hard timeout and a named, killable process group. PowerShell is refused with the fix.
- reviewer (agent_type == reviewer_agent): every shell segment must match reviewer_allow,
  redirects may only target /dev/null or reviewer_write_roots, heredocs and command
  substitution are refused, PowerShell is refused, and Write/Edit only reach the write roots.
  A scratch script (reviewer_script) or a reviewer_bounded command (node --test) is allowed only
  as `mergeq.py run --timeout N [--name X] [--cwd D] -- <command>`, so the Job Object's memory
  cap applies; read-only ruff and ty are on the allowlist.
- readonly (agent_type == readonly_agent): the reviewer's rules, but no scripts, no mergeq run,
  and nothing in readonly_refuse (pytest, unittest, node --test, make).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
MERGEQ = HERE / "mergeq.py"
EDIT_TOOLS = ("Write", "Edit", "NotebookEdit")
SHELL_TOOLS = ("Bash", "PowerShell")
TIMEOUT_PREFIX = re.compile(r"(^|[;&|(]\s*)timeout\s+(-\S+\s+)*(\d+)([smhd]?)\s")
MERGEQ_CALL = re.compile(r"mergeq\.py[\"']?\s+(\w+)")
MERGEQ_HEAVY_OK = re.compile(r"mergeq\.py[\"']?\s+(run\s+(\S+\s+)*--heavy\b|next\b)")
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", ";;", "|&"}
REDIRECTS = {">", ">>", ">&", "&>", ">|", "&>>"}


HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?=\n|$)", re.S)
QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")


class Refuse(Exception):
    pass


def _code_only(cmd: str) -> str:
    """The command with heredoc bodies and quoted strings blanked: what the shell will run,
    not the text it passes around (commit messages, docs written through a heredoc)."""
    return QUOTED.sub("''", HEREDOC.sub("<<''", cmd))


def _config() -> dict:
    path = Path(os.environ.get("MERGEQ_CONFIG") or HERE / "mergeq.toml")
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _heavy_patterns(cfg: dict) -> list[re.Pattern[str]]:
    pats = []
    for stage in cfg.get("stages", {}).values():
        if stage.get("light"):
            continue
        words = stage["cmd"][:2]
        pats.append(r"\b" + r"\s+([^\s;&|]+\s+)*".join(re.escape(w) for w in words) + r"\b")
    pats += cfg.get("hook", {}).get("heavy_extra", [])
    return [re.compile(p) for p in pats]


def _roots(cfg: dict) -> list[Path]:
    roots = []
    for root in cfg.get("hook", {}).get("reviewer_write_roots", []):
        expanded = os.path.expandvars(root)
        if expanded and "$" not in expanded:
            roots.append(Path(expanded).resolve())
    return roots


def _under(path: str, roots: list[Path]) -> bool:
    if not path:
        return False
    if re.match(r"^/[a-zA-Z]/", path):  # Git Bash /c/... -> C:/...
        path = f"{path[1]}:{path[2:]}"
    target = Path(path).resolve()
    return any(target == r or r in target.parents for r in roots)


# --------------------------------------------------------------------------- reviewer


def _segments(cmd: str) -> list[list[str]]:
    if "<<" in cmd:
        raise Refuse(
            "heredocs are not allowed for this agent: Write the probe script to a temp dir and run it"
        )
    if "`" in cmd or "$(" in cmd:
        raise Refuse(
            "command substitution is not allowed for this agent: run the inner command on its own"
        )
    lexer = shlex.shlex(cmd.replace("\\", "/"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise Refuse(f"could not parse the command ({exc})") from None
    segs, cur = [], []
    for tok in tokens:
        if tok in SEPARATORS:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        segs.append(cur)
    return segs


# `python -I .../mergeq.py run --timeout N [--name X] [--cwd D] -- CMD`
BOUNDED = re.compile(
    r"^python[0-9.]*\s+-I\s+(?P<mq>\S*mergeq\.py)\s+run\s+--timeout\s+(?P<secs>\d+)"
    r"(\s+--name\s+[\w.@-]+)?(\s+--cwd\s+\S+)?\s+--\s+(?P<inner>\S.*)$"
)


def _check_reviewer_shell(cfg: dict, tool: str, cmd: str, readonly: bool = False) -> None:
    if tool == "PowerShell":
        raise Refuse("this agent uses Bash only (read-only allowlist); PowerShell is refused")
    hook = cfg.get("hook", {})
    allow = [re.compile(p) for p in hook.get("reviewer_allow", [])]
    script_pat = re.compile(hook.get("reviewer_script", r"$^"))
    refuse = [re.compile(p) for p in hook.get("readonly_refuse", [])]
    bounded = [re.compile(p) for p in hook.get("reviewer_bounded", [])]
    max_timeout = int(hook.get("reviewer_max_timeout", 1800))
    roots = _roots(cfg)
    for seg in _segments(cmd):
        words: list[str] = []
        i = 0
        while i < len(seg):
            tok = seg[i]
            if re.fullmatch(r"\d", tok) and i + 1 < len(seg) and seg[i + 1] in REDIRECTS:
                i += 1  # the fd of `2>&1` / `2>/dev/null`
                continue
            if tok in REDIRECTS or tok == "<":
                target = seg[i + 1] if i + 1 < len(seg) else ""
                i += 2
                if tok == "<" or target in ("/dev/null", "1", "2") or _under(target, roots):
                    continue
                raise Refuse(f"redirect to {target!r} is outside the scratch roots")
            words.append(tok)
            i += 1
        while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", words[0]):
            words = words[1:]  # leading VAR=value assignments
        if not words:
            continue
        text = " ".join(words)
        if readonly and (any(p.search(text) for p in refuse) or script_pat.search(text)):
            raise Refuse("the read-only agent runs no tests, scripts or code")
        b = BOUNDED.match(text)
        if b:
            if (
                readonly
                or _under(b.group("mq"), roots)
                or not 0 < int(b.group("secs")) <= max_timeout
            ):
                raise Refuse(
                    f"mergeq run: --timeout 1..{max_timeout}, the repo's mergeq.py, not read-only"
                )
            text = b.group("inner")
        m = script_pat.search(text)
        if m and not b:
            raise Refuse(
                "a bare script has no memory limit: run it as `python -I devtools/mergeq/mergeq.py "
                "run --timeout 300 -- <command>`"
            )
        if m:
            if _under(m.group("script"), roots):
                continue
            raise Refuse(
                f"probe scripts must live under the scratch roots, not {m.group('script')!r}"
            )
        if b and any(p.search(text) for p in bounded):
            continue
        if not b and any(p.search(text) for p in bounded):
            raise Refuse(
                "run this bounded: `python -I devtools/mergeq/mergeq.py run --timeout 300 -- ...`"
            )
        if not any(p.search(text) for p in allow):
            raise Refuse(f"{words[0]!r} is not on this agent's read-only allowlist ({text[:80]!r})")


# --------------------------------------------------------------------------- everyone


def _wrap(cfg: dict, event: dict, cmd: str) -> dict:
    m = TIMEOUT_PREFIX.search(cmd)
    seconds = int(cfg.get("hook", {}).get("default_timeout", 600))
    if m:
        seconds = int(m.group(3)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(4)]
    who = event.get("agent_type") or "main"
    where = Path(event.get("cwd") or os.getcwd()).name
    name = re.sub(r"[^A-Za-z0-9_.@-]", "_", f"{who}@{where}")
    mergeq = shlex.quote(MERGEQ.as_posix())
    wrapped = (
        f"python -I {mergeq} run --timeout {seconds} --name {name} -- bash -c {shlex.quote(cmd)}"
    )
    tool_input = dict(event.get("tool_input") or {})
    tool_input["command"] = wrapped
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": tool_input}}


def check(event: dict, cfg: dict) -> dict | None:
    """Raise Refuse to block; return a hook JSON object to rewrite; None to allow."""
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    hook = cfg.get("hook", {})
    agent = event.get("agent_type")
    readonly = bool(agent) and agent == hook.get("readonly_agent", "bob-investigator")
    reviewer = readonly or agent == hook.get("reviewer_agent", "bob-reviewer")
    subagent = bool(event.get("agent_id") or event.get("agent_type"))
    if tool in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if reviewer and not _under(path, _roots(cfg)):
            raise Refuse(
                f"this agent is read-only; {path} is outside the scratch roots. Report the fix instead"
            )
        return None
    if tool not in SHELL_TOOLS:
        return None
    cmd = tool_input.get("command", "")
    if reviewer:
        _check_reviewer_shell(cfg, tool, cmd, readonly)
    code = _code_only(cmd)
    if not subagent:
        for pattern in hook.get("heavy_exempt", []):
            code = re.sub(pattern, "", code)
    heavy = next((p.pattern for p in _heavy_patterns(cfg) if p.search(code)), None)
    if heavy:
        if subagent:
            raise Refuse(
                f"heavy suites run in the merge queue, not in an agent (matched {heavy!r}). Run "
                "targeted tests (single files or -k) instead; the orchestrator gates your branch."
            )
        if not MERGEQ_HEAVY_OK.search(cmd):
            raise Refuse(
                f"this is a heavy suite (matched {heavy!r}). Run it under the machine-wide lock: "
                "`python -I devtools/mergeq/mergeq.py run --heavy --timeout <s> -- <command>`, "
                "or submit it to the queue."
            )
    if MERGEQ_CALL.search(cmd):
        return None
    if any(re.search(p, code) for p in hook.get("needs_timeout", [])):
        if tool == "PowerShell":
            raise Refuse(
                "test runs need a hard timeout: use `python -I devtools/mergeq/mergeq.py run "
                "--timeout 600 -- <command>` (timeout.exe in PowerShell is a sleep), or use Bash."
            )
        return _wrap(cfg, event, cmd)
    return None


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except ValueError as exc:
        print(f"mergeq hook: unreadable hook input ({exc}); refusing", file=sys.stderr)
        return 2
    if event.get("tool_name", "") in EDIT_TOOLS and not event.get("agent_type"):
        return 0  # never block the main session's edits: they are how a broken hook gets fixed
    try:
        out = check(event, _config())
    except Refuse as why:
        print(f"mergeq: {why}", file=sys.stderr)
        return 2
    except Exception as exc:  # fail closed: a broken hook must not silently allow
        print(
            f"mergeq hook is broken ({exc!r}); refusing until it is fixed. Repair "
            "devtools/mergeq/hook.py or mergeq.toml (the Edit tool is not blocked).",
            file=sys.stderr,
        )
        return 2
    if out is not None:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
