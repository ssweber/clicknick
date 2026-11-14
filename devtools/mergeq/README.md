# mergeq: local merge queue and process guard

Tooling for agent-driven development on one machine: gate branches (alone or as a train)
against the base branch, land exactly the tested merge, and keep heavy test runs serialized,
timed and killable. The orchestration procedure that uses it is the `/bob` skill
(`.claude/skills/bob/`); the builder and reviewer roles are `.claude/agents/bob-*.md`.

Stdlib only (Python 3.11+). Everything repo-specific lives in `mergeq.toml`; copy this folder
to another repo and edit that file.

```
python -I devtools/mergeq/mergeq.py <command>
```

Files: `mergeq.py` (the tool), `hook.py` (PreToolUse guard), `test_hook.py`,
`mergeq.toml` (the only repo-specific file).

| command | what it does |
|---|---|
| `submit --id X --branch B [--branch C ...] [--stages P]` | queue a job; several branches = a train, merged in order. `P` is a preset (`fast`, `heavy`, `train`, `default`) or a comma list of stages |
| `next` | run the oldest job: merge onto the base in a scratch worktree, `install`, then stages cheapest first under the heavy lock, stop at the first failure. One job per call: launch it in the background to be notified. Exit 0 pass, 1 fail, 2 conflict (`conflict_branch` names it), 3 empty, 4 error |
| `land --id X` | fast-forward the base to `refs/mergeq/X`, the exact merge that passed. Refuses if the base or a branch moved since the test, or the main checkout has tracked changes on the base |
| `status` / `cancel --id X` | queue state and the lock; cancel kills a running job's process trees and cleans up. The runner's pid file also records its creation time: a stale file (process gone, or the pid reused after a reboot) is reported and removed, and kills nothing |
| `run [--heavy] [--timeout S] [--name N] [--cwd D] -- CMD` | run CMD as a kill-on-close process group (Windows Job Object; process group elsewhere). `--heavy` waits for and holds the machine-wide lock; without it the run takes one of `targeted_slots`. `--timeout` starts once it has either. Exit = CMD's, 124 timeout, 125 lock or slot wait expired |
| `ps [--all]` | mergeq-run groups (runner pid, process count, peak memory, cwd); `--all` adds test processes mergeq did not start |
| `reap --name PREFIX` / `reap --unmanaged [--match RE] [--dry-run]` | kill every group whose name starts with PREFIX / stray processes under the repo or worktrees (language servers excluded) |
| `lock status` | free, or who holds it; how many targeted slots are in use |
| `worktree new NAME [--base REF]` / `rm NAME [--force]` / `list` | `<worktree_root>/NAME` on `<branch_prefix>NAME`; `rm` refuses unless landed and clean |
| `note --id X --kind handoff\|review\|ledger [--file F]` | append to `<home>/jobs/X/<KIND>.md` (stdin by default) |

## Guarantees

- **Base only moves to tested trees.** `land` is fast-forward-only to the commit the gate ran on.
- **No stale lock.** The heavy lock is an OS file lock held by the running process
  (`msvcrt.locking` / `flock`); the OS releases it when that process exits or dies.
  `<lock>.owner` is just a label.
- **Targeted runs share a few slots.** `run` without `--heavy` takes one of `targeted_slots`
  (OS file locks beside the heavy lock, freed the same way) and waits up to `targeted_wait`,
  so parallel builders and reviewers queue instead of piling onto the machine. Gate stages and
  `--heavy` runs take no slot, and neither does a run nested inside one.
- **No orphans.** Each command runs in a Job Object with kill-on-close: a timeout, `cancel`,
  `reap`, or the runner itself dying kills the whole tree. `job_memory_mb` caps a job's memory.
  One gap: Python's Windows launchers (the WindowsApps `python` alias, a venv `python.exe`)
  run the interpreter in a job of their own that lets children break away. A timeout or
  `cancel` still gets them (the parent tree is walked first), but if the runner itself is
  killed such escapees survive: `ps --all` / `reap --unmanaged` find them. `uv run ...`
  stays contained.
- **The desktop stays usable under load (Windows).** Every command starts at below-normal
  priority and its descendants inherit it, so a gate gives way to the terminal and anything
  else running at normal priority. Stage timeouts are wall-clock, so heavy desktop use can
  slow a gate towards them.
- **Agents can't start heavy suites, and every test run is timed and killable.** `hook.py`
  (PreToolUse on Bash/PowerShell/Write/Edit, wired in `.claude/settings.json`):
  - refuses non-light stage commands and `[hook].heavy_extra` in subagents, and requires the
    main session to use `run --heavy` (the lock) or the queue, apart from `[hook].heavy_exempt`
    in the main session;
  - rewrites `needs_timeout` commands (pytest) in Bash to
    `mergeq.py run --timeout N --name <agent>@<worktree> -- bash -c '...'`, so each run is a
    named job (`ps`, `reap --name bob-builder@drum`); PowerShell gets a refusal with the fix;
  - for the reviewer agent (`agent_type == reviewer_agent`): shell segments must match
    `reviewer_allow`, redirects only to /dev/null or `reviewer_write_roots`, no heredocs,
    `$(...)` or PowerShell, and Write only under the write roots. Scratch scripts
    (`reviewer_script`) and `reviewer_bounded` commands run only as
    `mergeq.py run --timeout N [--name X] [--cwd D] -- <command>` (N at most
    `reviewer_max_timeout`), so the Job Object's memory cap applies; the bare form is refused.
    ruff check, ruff format --check and ty check are allowed (no `--fix`, no `--config`);
  - for the read-only agent (`agent_type == readonly_agent`, `bob-investigator`): the
    reviewer's rules minus scripts, `mergeq run` and anything in `readonly_refuse` (pytest,
    unittest, make). For investigations that must not run tests;
  - matches heavy/timeout patterns on the command with heredoc bodies and quoted strings
    blanked, so commit messages and docs written through a heredoc don't trip it;
  - fails closed: if the hook breaks, shell calls are refused with the error (the main
    session's Edit tool is never blocked, so it can be repaired).
  `test_hook.py` pins the decisions on recorded payloads.

## State (`home` in mergeq.toml, outside the repo)

`queue/ running/ done/<id>.json (+ .job.json) logs/<id>/<stage>.log cand/ jobs/<id>/ procs/`.
`done/<id>.json` has base/branch/merged shas, per-stage rc, seconds, timeout, peak memory,
failing test ids and the log tail.

## New repo checklist

1. Copy this folder; edit `mergeq.toml` (base, paths, stages with timeouts, `light` stages,
   presets, hook patterns, `[ps]` names).
2. Add the PreToolUse hook to `.claude/settings.json`; copy the two agent files and the `bob`
   skill, and write the skill's `profile.md` for the repo.
3. Keep `experimental.cacheTtl: 1h` in the agent files (Claude Code 2.1.248+; older:
   `"subagentPromptCacheTtl": "1h"` in `~/.claude/settings.json`). Resumed builders and
   reviewers stay cached across long gate stages; the default is 5 minutes.
4. `timeout 120 uv run pytest devtools/mergeq -q`, then reload hooks (`/hooks` or a fresh
   session) and check that a heavy stage command is refused and a pytest comes back wrapped.
