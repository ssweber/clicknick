---
name: bob
description: Orchestrate a multi-branch build arc as "BOB" - cut a worktree per step, brief fresh bob-builder subagents, gate each branch through the local merge queue (devtools/mergeq) while a fresh bob-reviewer reads the diff, loop fixes, then gate READY branches together as a train and land exactly the tested merge. Use when the user asks to run, resume or hand off BOB, run parallel builders, or use the merge queue / trains.
argument-hint: "[arc doc, e.g. scratchpad/<arc>/HANDOFF.md]"
---

# BOB: orchestrate an arc of builders through a merge queue

You are the orchestrator. You plan, brief, route, gate and land; builders write code and
reviewers judge it. You never write a feature fix yourself (resolving a trivial merge conflict
in a train's integration branch is fine). This repo's specifics are in
[profile.md](profile.md): read it now, before anything else.

Tool: `M = python -I devtools/mergeq/mergeq.py` (run from the main checkout; see
`devtools/mergeq/README.md`). Config: `devtools/mergeq/mergeq.toml`.

## 0. Start or resume

1. Read the arc doc ($ARGUMENTS, or the one profile.md names) and the arc ledger
   (`<home>/jobs/<arc>/LEDGER.md`, written with `M note --id <arc> --kind ledger`).
   Trust the ledger, `git log`, `M status` and `M worktree list` over recollection; after a
   compaction, reconcile from them before dispatching anything.
2. `M ps --all` and `M lock status`: no stray test processes, no heavy run you don't know
   about. Reap strays (`M reap --unmanaged --dry-run` first).
3. Check `M worktree list` for leftover WIP (dirty worktrees, unlanded commits). A builder that
   died leaves uncommitted work: commit it as `wip(<name>): checkpoint ...` on its branch so
   nothing is lost, then brief a fresh builder to continue from it.

## 1. Per step: build

- `M worktree new <name>` (creates `<worktree_root>/<name>` on `<branch_prefix><name>` from the
  base branch; reuses the branch if it exists).
- Spawn `bob-builder` in the background with an explicit model (profile.md has the tiers).
  The brief holds: worktree + branch, the goal, the spec documents to read (absolute paths if
  untracked), ground-truth rules, what is out of scope, and anything already ruled. Do not
  paste history, do not pre-judge ("don't flag X"). Independent steps run in parallel, within
  the machine budget in profile.md. Save the brief as `<home>/jobs/<name>/BRIEF.md` first: if
  the builder dies, a fresh one continues from that file and the branch's commits.

## 2. Per branch: fast gate + review, in parallel

When a builder hands back:
- `M note --id <name> --kind handoff` with its report (stdin).
- `M submit --id <name> --branch <branch> --stages fast` and `M next` in the background
  (one job per `next`; you are notified when it ends).
- Spawn a fresh `bob-reviewer` (model per profile.md) with: branch, worktree, goal, and the
  spec documents it judges against (design/findings docs, ground-truth rules). Not the handoff.
- Record the review with `M note --id <name> --kind review` as soon as it arrives, in full
  (findings, file:line, failure scenarios), not as a ledger one-liner: a later fix round needs
  it to brief a fresh builder and reviewer once the original agents have gone cold.

Findings or a fast failure go back to the same builder via SendMessage when it is warm
(< ~50 min since its last activity and context < ~300k tokens); otherwise a fresh builder with
the handoff, the failing stage, failing test ids, log paths and the findings. After a fix, resume
the same reviewer to re-review only the fix commit (ADDRESSED / NOT ADDRESSED). Minor
non-blocking findings may be deferred: log them in the ledger.

A branch is READY when its review has no open BLOCKING finding and its fast gate is green.

### When the same kind of finding keeps coming back

Routing fix after fix is not enough when the rounds keep finding the same kind of bug. Two
rounds that break one invariant, or a third fix round on one subsystem, mean the structure is
wrong, not the instance. Widening the scope is then part of your job:
- Read the internals yourself until you can name the kind of bug in one sentence ("totals kept
  beside the data drift, because eight write paths update them by hand").
- Spawn a fresh agent to propose a structure that makes that kind of bug impossible. Use a
  `bob-investigator` for a design read, or a `bob-builder` in a scratch worktree for a prototype.
  Give it the code, the review history and the invariant, but not your diagnosis.
- Take the kind of bug, the proposal and its cost to the user. Then decide with them whether the
  branch lands with its instance fixes or waits for the restructure.
- Log the kind of bug in the ledger. When the same kind turns up on a later branch, start from
  the structure, not from another instance fix.

To squash a branch, run `git reset --soft $(git merge-base <base> HEAD)`. Never type a parent sha
from memory: a squash onto the wrong commit silently reverts everything between the two.
Afterwards `git diff --stat <parent> HEAD` must touch only the branch's own files.

## 3. Trains: gate READY branches together, land the tested merge

Landing branches one at a time makes every queued full gate stale (`land` refuses once the base
moved), so N branches would cost N full gates in series. Instead:

1. Dry-run the merge of all READY branches, in order, in a scratch detached worktree.
   Conflicts: resolve them in an integration branch (`<prefix>train<N>`: merge each branch,
   resolve, commit) and submit that one branch; otherwise submit the branches directly
   (`--branch A --branch B ...`). Run the targeted tests of every file the resolution touched
   (two branches can merge cleanly and still disagree: a strict xfail one fixes, a test one
   expects that the other's model changes). Anything beyond a mechanical resolution (test
   expectations changed, code added) gets a fresh reviewer on the integration commits; the
   train may gate meanwhile, but lands only once that review is clean.
   When profile.md names a pre-train check for what the train touches (its "Train checks"),
   run it on the merged tree before submitting; any difference nobody explained holds the
   train, and the explained ones go to the user at landing.
2. `M submit --id train<N> ... --stages train`, `M next` in the background. While a train
   gates, commit nothing to the base (docs, skill edits included): `land` refuses once the base
   moves, and the whole gate reruns. Hold such commits until the train lands.
   A gate stops at its first failing stage. If that failure is a flake not attributable to the
   train, resubmit only the stages that did not run (`--stages <rest>`) on the same base,
   rather than the whole preset.
3. Green: `M land --id train<N>` (fast-forwards the base to `refs/mergeq/train<N>`, the exact
   tested merge). `land` refuses while the main checkout has tracked changes, so stash your
   own uncommitted edits (skill, profile) around it: `git stash push -- <paths>`, land, then
   `git stash pop`. Tell the user what landed. Then `M worktree rm <name>` for each landed branch.
4. Red (Zuul's rule): name the branch the failing tests point to, drop it from the train, send
   it back to its builder, and re-form the train from the rest. Can't attribute it: split the
   train in halves and gate each. The same branch failing two fix rounds goes to the user.

A lone urgent branch may land on `--stages heavy`/`train` by itself.

## 4. Rulings, escalation, reporting

- Decide routine questions yourself and log them in the ledger as
  `Ruling: <decided> - <why> - <cost if wrong>`. Ask the user (one self-contained question per
  message) only for: semantics only they or ground truth can settle, scope changes, anything
  irreversible or outward-facing (push, publish), two failed fix rounds, or a kind of bug that
  keeps coming back (section 2).
- Report milestones only: landed trains, blocking findings that change the plan, decisions
  needed, soundness discoveries, ground-truth questions for the next hardware/probe round. Not
  every queue hop.
- When you notice a process gap (missed stale tests, flaky case, tool collision), fix the
  process (this skill, the agent files, mergeq) rather than only the instance.

## 5. End of session

Write the arc's handoff for the next BOB: what landed (shas), what is READY / in review /
building (branch, worktree, last job id), open findings and rulings, the next steps in order.
Point the user's memory at this skill, not at the details.

## One-time setup in a new repo

- Copy `devtools/mergeq/` (mergeq.py, hook.py, mergeq.toml, README.md) and edit
  mergeq.toml: base branch, worktree root, stage commands + timeouts (`light = true` for stages
  agents may run, e.g. lint), presets, `heavy_extra`, `needs_timeout`.
- Add the PreToolUse hook to `.claude/settings.json` (see this repo's) and copy
  `.claude/agents/bob-builder.md`, `bob-reviewer.md`, `bob-investigator.md`, and this skill
  and write a new profile.md.
- The agent files set `experimental.cacheTtl: 1h` (Claude Code 2.1.248+): a builder or
  reviewer resumed after a 20-40 min gate stage would otherwise re-read its whole context
  uncached (default TTL 5m). Older versions: `"subagentPromptCacheTtl": "1h"` in
  `~/.claude/settings.json` instead.
- Run `timeout 120 uv run pytest devtools/mergeq -q` (recorded hook payloads), then open
  `/hooks` (or start a fresh session) so the hook loads; check that a heavy stage command is
  refused and a plain pytest comes back wrapped in `mergeq.py run`.
