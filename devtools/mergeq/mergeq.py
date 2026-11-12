"""mergeq: a local merge queue and process guard for agent-driven development.

Gate one branch or a train of branches against the base branch, land exactly the
tested merge, and run heavy commands under one machine-wide lock with hard
timeouts. Stdlib only; run with `python -I devtools/mergeq/mergeq.py ...`.

    submit --id X --branch B [--branch C ...] [--stages fast|train|lint,test,...]
    next                       run the oldest queued job (launch in the background)
    land --id X                fast-forward the base branch to X's tested merge
    status | cancel --id X
    run [--heavy] [--timeout S] [--name N] -- CMD...
                               run CMD in a kill-on-close process group, optionally
                               under the heavy lock; exit 124 on timeout
    ps [--all] | reap (--name N | --unmanaged [--match RE] [--dry-run])
    lock status
    worktree new NAME [--base REF] | rm NAME [--force] | list
    note --id X --kind handoff|review|ledger [--file F]   (stdin if no --file)

Everything repo-specific is in mergeq.toml next to this file ($MERGEQ_CONFIG
overrides). See README.md for the workflow.

Exit codes: `next` 0 pass, 1 stage failed, 2 merge conflict, 3 queue empty,
4 runner error. `land` 0 landed, 4 refused. `run` the command's code, 124
timeout, 125 lock wait expired.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REF_PREFIX = "refs/mergeq/"
IS_WINDOWS = os.name == "nt"


# --------------------------------------------------------------------------- config


def _main_checkout() -> Path:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=HERE,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    return Path(common).parent


class Config:
    def __init__(self) -> None:
        path = Path(os.environ.get("MERGEQ_CONFIG") or HERE / "mergeq.toml")
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        self.raw = raw
        self.repo = _main_checkout()
        self.base: str = raw.get("base", "main")
        self.home = (self.repo / raw.get("home", "../mergeq")).resolve()
        self.worktree_root = (self.repo / raw.get("worktree_root", "../worktrees")).resolve()
        self.branch_prefix: str = raw.get("branch_prefix", "")
        self.lock_file = (self.repo / raw.get("lock_file", "../.mergeq-heavy.lock")).resolve()
        self.lock_wait: int = int(raw.get("lock_wait", 3 * 3600))
        self.targeted_slots: int = int(raw.get("targeted_slots", 0))
        self.targeted_wait: int = int(raw.get("targeted_wait", 1800))
        self.job_memory_mb: int = int(raw.get("job_memory_mb", 0))
        self.install: dict | None = raw.get("install")
        self.stages: dict[str, dict] = raw.get("stages", {})
        self.presets: dict[str, list[str]] = raw.get("presets", {})
        self.hook: dict = raw.get("hook", {})
        self.ps: dict = raw.get("ps", {})

    def dirs(self) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
        names = ("queue", "running", "done", "logs", "cand", "jobs", "procs")
        return tuple(self.home / d for d in names)  # type: ignore[return-value]

    def expand_stages(self, spec: str | None) -> list[str]:
        names = spec.split(",") if spec else self.presets.get("default", list(self.stages))
        out = [s for name in names for s in self.presets.get(name, [name])]
        return list(dict.fromkeys(out))


CFG: Config


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _git(
    *args: str, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd or CFG.repo, text=True, capture_output=True, check=check
    )


def _sha(rev: str, cwd: Path | None = None) -> str:
    return _git("rev-parse", "--verify", rev, cwd=cwd).stdout.strip()


def _resolve_cmd(cmd: list[str]) -> list[str]:
    return [shutil.which(cmd[0]) or cmd[0], *cmd[1:]]


def _procs_dir() -> Path:
    return CFG.home / "procs"


# --------------------------------------------------------------------------- process groups
# Windows: a named Job Object with KILL_ON_JOB_CLOSE; the child starts suspended, joins the
# job, then resumes, so every grandchild is in the job. Closing the handle (normal exit, crash,
# or this process being killed) kills the whole tree. Elsewhere: a new session + killpg.
# On Windows the child starts below normal priority so the desktop stays responsive under a
# gate. Descendants inherit that from their parent, including any that break away from the job.

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            (n, ctypes.c_ulonglong)
            for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")
        ]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("Basic", _BasicLimits),
            ("Io", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.OpenJobObjectW.restype = wintypes.HANDLE
    _k32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _k32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

    _EXTENDED_LIMIT_INFO = 9
    _BASIC_PROCESS_ID_LIST = 3
    _KILL_ON_JOB_CLOSE = 0x2000
    _LIMIT_JOB_MEMORY = 0x200
    _JOB_QUERY_TERMINATE = 0x0004 | 0x0008
    _CREATE_SUSPENDED = 0x00000004
    _CREATE_NEW_PROCESS_GROUP = 0x00000200

    def _job_name(name: str) -> str:
        return "mergeq-" + re.sub(r"[^A-Za-z0-9_.-]", "_", name)

    def _pid_alive(pid: int) -> bool:
        handle = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = wintypes.DWORD()
        ok = _k32.GetExitCodeProcess(handle, ctypes.byref(code))
        _k32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE

    _k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4

    def _proc_start(pid: int) -> str | None:
        """When the process was created (FILETIME ticks), or None if it is not running."""
        if not _pid_alive(pid):  # an exited process keeps its times while a handle is open
            return None
        handle = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        ok = _k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))
        _k32.CloseHandle(handle)
        if not ok:
            return None
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)

    class _PidList(ctypes.Structure):
        _fields_ = [
            ("Assigned", wintypes.DWORD),
            ("Listed", wintypes.DWORD),
            ("Ids", ctypes.c_size_t * 4096),
        ]

    def _job_pids(handle: int) -> list[int]:
        info = _PidList()
        if not _k32.QueryInformationJobObject(
            handle, _BASIC_PROCESS_ID_LIST, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            return []
        return [int(p) for p in info.Ids[: info.Listed]]

    def _job_peak_mb(handle: int) -> int:
        info = _ExtendedLimits()
        if not _k32.QueryInformationJobObject(
            handle, _EXTENDED_LIMIT_INFO, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            return 0
        return info.PeakJobMemoryUsed // (1024 * 1024)

    class ProcGroup:
        """A child process and its descendants, killed together."""

        def __init__(
            self, cmd: list[str], name: str, cwd: Path, env: dict[str, str], stdout=None
        ) -> None:
            self.name = name
            self.job = _k32.CreateJobObjectW(None, _job_name(name))
            if not self.job:
                raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
            info = _ExtendedLimits()
            info.Basic.LimitFlags = _KILL_ON_JOB_CLOSE
            if CFG.job_memory_mb:
                info.Basic.LimitFlags |= _LIMIT_JOB_MEMORY
                info.JobMemoryLimit = CFG.job_memory_mb * 1024 * 1024
            if not _k32.SetInformationJobObject(
                self.job, _EXTENDED_LIMIT_INFO, ctypes.byref(info), ctypes.sizeof(info)
            ):
                raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
            self.proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT if stdout is not None else None,
                creationflags=(
                    _CREATE_SUSPENDED
                    | _CREATE_NEW_PROCESS_GROUP
                    | subprocess.BELOW_NORMAL_PRIORITY_CLASS
                ),
            )
            handle = int(vars(self.proc)["_handle"])  # Windows-only Popen attribute
            if not _k32.AssignProcessToJobObject(self.job, handle):
                err = ctypes.get_last_error()
                self.proc.kill()
                raise OSError(err, "AssignProcessToJobObject failed")
            _ntdll.NtResumeProcess(handle)

        def wait(self, timeout: float | None) -> int:
            return self.proc.wait(timeout=timeout)

        def kill(self) -> None:
            # Python's Windows launchers (the WindowsApps alias, venv python.exe) run the real
            # interpreter in a job of their own that lets its children break away silently, so
            # walk the parent tree first while it is intact, then end everything left in the job.
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], capture_output=True
            )
            _k32.TerminateJobObject(self.job, 1)
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass

        def peak_mb(self) -> int:
            return _job_peak_mb(self.job) if self.job else 0

        def close(self) -> None:
            if self.job:
                _k32.CloseHandle(self.job)  # kill-on-close takes any survivors with it
                self.job = None

    def _open_job(name: str) -> int | None:
        return _k32.OpenJobObjectW(_JOB_QUERY_TERMINATE, False, _job_name(name)) or None

    def _terminate_job(name: str) -> bool:
        handle = _open_job(name)
        if not handle:
            return False
        _k32.TerminateJobObject(handle, 1)
        _k32.CloseHandle(handle)
        return True

    def _job_info(name: str) -> tuple[list[int], int] | None:
        handle = _open_job(name)
        if not handle:
            return None
        try:
            return _job_pids(handle), _job_peak_mb(handle)
        finally:
            _k32.CloseHandle(handle)

else:
    import signal

    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _proc_start(pid: int) -> str | None:
        """When the process was created (`ps` lstart text), or None if it is not running."""
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], text=True, capture_output=True
        ).stdout.strip()
        return out or None

    class ProcGroup:  # type: ignore[no-redef]
        def __init__(
            self, cmd: list[str], name: str, cwd: Path, env: dict[str, str], stdout=None
        ) -> None:
            self.name = name
            self.proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT if stdout is not None else None,
                start_new_session=True,
            )

        def wait(self, timeout: float | None) -> int:
            return self.proc.wait(timeout=timeout)

        def kill(self) -> None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except OSError:
                pass
            self.proc.wait()

        def peak_mb(self) -> int:
            return 0

        def close(self) -> None:
            if self.proc.poll() is None:
                self.kill()

    def _terminate_job(name: str) -> bool:
        entry = _procs_dir() / f"{name}.json"
        if not entry.exists():
            return False
        pgid = json.loads(entry.read_text(encoding="utf-8")).get("child_pid")
        try:
            os.killpg(int(pgid), signal.SIGKILL)
        except (OSError, TypeError, ValueError):
            return False
        return True

    def _job_info(name: str) -> tuple[list[int], int] | None:
        return None


def _register(name: str, cmd: list[str], cwd: Path, heavy: bool, child_pid: int) -> Path:
    d = _procs_dir()
    d.mkdir(parents=True, exist_ok=True)
    entry = d / f"{name}.json"
    entry.write_text(
        json.dumps(
            {
                "name": name,
                "pid": os.getpid(),
                "child_pid": child_pid,
                "cmd": cmd,
                "cwd": str(cwd),
                "heavy": heavy,
                "started": _now(),
                "owner": os.environ.get("MERGEQ_OWNER", ""),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return entry


def run_group(
    cmd: list[str],
    *,
    name: str,
    cwd: Path,
    timeout: int | None,
    env: dict[str, str] | None = None,
    log: Path | None = None,
    heavy: bool = False,
) -> tuple[int, float, bool, int]:
    """Run cmd as a killable group. Returns (rc, seconds, timed_out, peak_mb)."""
    env = env if env is not None else dict(os.environ)
    start = time.monotonic()
    fh = None
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        fh = log.open("w", encoding="utf-8", errors="replace")
        fh.write(f"$ {' '.join(cmd)}  (cwd {cwd}, timeout {timeout}s, {_now()})\n")
        fh.flush()
    group = ProcGroup(_resolve_cmd(cmd), name, cwd, env, stdout=fh)
    entry = _register(name, cmd, cwd, heavy, group.proc.pid)
    timed_out = False
    try:
        try:
            rc = group.wait(timeout)
        except subprocess.TimeoutExpired:
            group.kill()
            rc, timed_out = 124, True
            msg = f"\n*** mergeq: TIMEOUT after {timeout}s: process tree killed ***\n"
            (fh.write(msg) if fh else sys.stderr.write(msg))
        except KeyboardInterrupt:
            group.kill()
            raise
        peak = group.peak_mb()
    finally:
        group.close()
        entry.unlink(missing_ok=True)
        if fh:
            fh.close()
    return rc, round(time.monotonic() - start, 1), timed_out, peak


# --------------------------------------------------------------------------- heavy lock
# An OS file lock held by the process that runs the heavy command: the OS drops it when
# that process exits or dies, so a stale lock cannot exist. <lock>.owner is only a label.


def _try_file_lock(path: Path):
    """The open, locked file, or None if another holder has it. Never blocks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+b")
    try:
        if IS_WINDOWS:
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _release_file_lock(fh) -> None:
    try:
        if IS_WINDOWS:
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    fh.close()


def _owner_file() -> Path:
    return CFG.lock_file.with_name(CFG.lock_file.name + ".owner")


def lock_owner() -> str:
    try:
        return _owner_file().read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


class HeavyLock:
    def __init__(self, label: str) -> None:
        self.label = label
        self.fh = None

    def try_acquire(self) -> bool:
        fh = _try_file_lock(CFG.lock_file)
        if fh is None:
            return False
        self.fh = fh
        _owner_file().write_text(
            f"{self.label} pid={os.getpid()} since={_now()}\n", encoding="utf-8"
        )
        return True

    def acquire(self, wait: int) -> bool:
        deadline = time.monotonic() + wait
        announced = False
        while not self.try_acquire():
            if time.monotonic() > deadline:
                return False
            if not announced:
                print(
                    f"mergeq: waiting for the heavy lock (held by {lock_owner()})", file=sys.stderr
                )
                announced = True
            time.sleep(10)
        return True

    def release(self) -> None:
        if self.fh is None:
            return
        try:
            _owner_file().write_text("", encoding="utf-8")
        except OSError:
            pass
        _release_file_lock(self.fh)
        self.fh = None


# Targeted runs (`run` without --heavy) share targeted_slots slots, each its own OS file lock,
# so builders and reviewers cannot pile onto the cores a gate leaves free. A waiter holds
# nothing, and a slot frees when its holder exits or dies. Not first-come-first-served: whoever
# polls next takes a freed slot. A run started inside a held slot or the heavy lock takes none.
IN_SLOT_ENV = "MERGEQ_IN_SLOT"


def _slot_file(index: int) -> Path:
    return CFG.lock_file.with_name(f".targeted.{index}.lock")


class TargetedSlot:
    def __init__(self) -> None:
        self.fh = None

    def try_acquire(self) -> bool:
        for index in range(CFG.targeted_slots):
            fh = _try_file_lock(_slot_file(index))
            if fh is not None:
                self.fh = fh
                return True
        return False

    def acquire(self, wait: int) -> bool:
        if CFG.targeted_slots <= 0 or os.environ.get(IN_SLOT_ENV):
            return True
        deadline = time.monotonic() + wait
        announced = False
        while not self.try_acquire():
            if time.monotonic() > deadline:
                return False
            if not announced:
                print(
                    f"mergeq: waiting for a targeted slot ({CFG.targeted_slots} in use, "
                    "`mergeq ps` shows them); --timeout starts once it has one",
                    file=sys.stderr,
                )
                announced = True
            time.sleep(2)
        return True

    def release(self) -> None:
        if self.fh is not None:
            _release_file_lock(self.fh)
            self.fh = None


def _slots_in_use() -> int:
    used = 0
    for index in range(CFG.targeted_slots):
        fh = _try_file_lock(_slot_file(index))
        if fh is None:
            used += 1
        else:
            _release_file_lock(fh)
    return used


# --------------------------------------------------------------------------- queue


def _tail(log: Path, n: int = 60) -> list[str]:
    try:
        return log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


FAIL_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+)")


def _failing_tests(log: Path) -> list[str]:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return sorted({m.group(1) for line in text.splitlines() if (m := FAIL_LINE.match(line))})


def _branches(job: dict) -> list[str]:
    return job.get("branches") or [job["branch"]]


def cmd_submit(args: argparse.Namespace) -> int:
    stages = CFG.expand_stages(args.stages)
    unknown = [s for s in stages if s not in CFG.stages]
    if unknown:
        print(f"unknown stages: {unknown}; known: {list(CFG.stages)}", file=sys.stderr)
        return 4
    for branch in args.branch:
        _sha(branch)
    queue = CFG.home / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    job = {
        "id": args.id,
        "branches": args.branch,
        "stages": stages,
        "submitted": _now(),
        "note": args.note or "",
    }
    path = queue / f"{datetime.now():%Y%m%d-%H%M%S}-{args.id}.json"
    path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    print(f"queued {path.name}: {' + '.join(args.branch)} -> {','.join(stages)}")
    return 0


def cmd_next(_args: argparse.Namespace) -> int:
    queue, running, done, logs, cand_root, _jobs, _procs = CFG.dirs()
    jobs = sorted(queue.glob("*.json")) if queue.exists() else []
    if not jobs:
        print("queue empty")
        return 3
    running.mkdir(parents=True, exist_ok=True)
    done.mkdir(parents=True, exist_ok=True)
    job_path = running / jobs[0].name
    jobs[0].replace(job_path)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    jid = job["id"]
    branches = _branches(job)
    pid_file = running / f"{jid}.pid"
    # "<pid> <creation time>": cancel kills only a process that still has this creation time,
    # so a pid reused after a reboot is never taken for the runner.
    pid_file.write_text(f"{os.getpid()} {_proc_start(os.getpid()) or ''}", encoding="utf-8")
    result: dict = {
        **job,
        "branches": branches,
        "started": _now(),
        "stages_run": [],
        "failing_tests": [],
        "tail": [],
    }
    cand = cand_root / jid
    log_dir = logs / jid
    shutil.rmtree(log_dir, ignore_errors=True)
    lock = HeavyLock(f"mergeq job {jid}")

    def finish(status: str, rc: int) -> int:
        result.update(status=status, finished=_now())
        (done / f"{jid}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        job_path.replace(done / f"{jid}.job.json")
        keys = ("id", "status", "failed_stage", "conflict_branch", "failing_tests")
        print(json.dumps({k: result[k] for k in keys if k in result}, indent=2))
        print(f"result: {done / (jid + '.json')}")
        return rc

    try:
        if cand.exists():
            _git("worktree", "remove", "--force", str(cand), check=False)
            shutil.rmtree(cand, ignore_errors=True)
        result["base_sha"] = _sha(CFG.base)
        result["branch_shas"] = {b: _sha(b) for b in branches}
        _git("worktree", "add", "--detach", str(cand), result["base_sha"])
        for branch in branches:
            merge = _git("merge", "--no-edit", result["branch_shas"][branch], cwd=cand, check=False)
            if merge.returncode != 0:
                result["conflict_branch"] = branch
                result["conflicts"] = _git(
                    "diff", "--name-only", "--diff-filter=U", cwd=cand, check=False
                ).stdout.split()
                result["tail"] = (merge.stdout + merge.stderr).splitlines()[-40:]
                _git("merge", "--abort", cwd=cand, check=False)
                return finish("conflict", 2)
        result["merged_sha"] = _sha("HEAD", cwd=cand)

        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")}
        if CFG.install:
            rc, secs, to, _ = run_group(
                CFG.install["cmd"],
                name=f"{jid}-install",
                cwd=cand,
                timeout=int(CFG.install.get("timeout", 900)),
                env=env,
                log=log_dir / "install.log",
            )
            result["stages_run"].append(
                {"name": "install", "rc": rc, "seconds": secs, "timed_out": to}
            )
            if rc != 0:
                result["failed_stage"] = "install"
                result["tail"] = _tail(log_dir / "install.log")
                return finish("fail", 1)

        if not lock.acquire(CFG.lock_wait):
            result["failed_stage"] = "lock"
            return finish("error", 4)
        try:
            for name in job["stages"]:
                stage = CFG.stages[name]
                log = log_dir / f"{name}.log"
                rc, secs, to, peak = run_group(
                    stage["cmd"],
                    name=f"{jid}-{name}",
                    cwd=cand,
                    timeout=int(stage.get("timeout", 1200)),
                    env=env,
                    log=log,
                    heavy=True,
                )
                result["stages_run"].append(
                    {
                        "name": name,
                        "rc": rc,
                        "seconds": secs,
                        "timed_out": to,
                        "peak_mb": peak,
                        "log": str(log),
                    }
                )
                if rc != 0:
                    result["failed_stage"] = name
                    result["failing_tests"] = _failing_tests(log)
                    result["tail"] = _tail(log)
                    return finish("fail", 1)
                # A stage that rewrites tracked files (e.g. a formatter) means a branch is not clean.
                dirty = _git(
                    "status", "--porcelain", "--untracked-files=no", cwd=cand, check=False
                ).stdout.splitlines()
                if dirty:
                    result["failed_stage"] = name
                    result["tail"] = [
                        "stage modified tracked files (branch not lint-clean):",
                        *dirty[:40],
                    ]
                    return finish("fail", 1)
        finally:
            lock.release()
        _git(
            "update-ref", REF_PREFIX + jid, result["merged_sha"]
        )  # keep the tested merge until it lands
        return finish("pass", 0)
    except Exception as exc:  # report, never hang
        result["error"] = repr(exc)
        return finish("error", 4)
    finally:
        _git("worktree", "remove", "--force", str(cand), check=False)
        shutil.rmtree(cand, ignore_errors=True)
        pid_file.unlink(missing_ok=True)


def cmd_land(args: argparse.Namespace) -> int:
    jid = args.id
    path = CFG.home / "done" / f"{jid}.json"
    if not path.exists():
        print(f"no result for {jid}", file=sys.stderr)
        return 4
    r = json.loads(path.read_text(encoding="utf-8"))
    if r.get("status") != "pass":
        print(f"{jid} did not pass (status {r.get('status')})", file=sys.stderr)
        return 4
    if r.get("landed"):
        print(f"{jid} already landed at {r['landed']}")
        return 0
    refusals = []
    base_now = _sha(CFG.base)
    if base_now != r["base_sha"]:
        refusals.append(
            f"{CFG.base} moved: tested on {r['base_sha'][:10]}, now {base_now[:10]}; resubmit"
        )
    for branch, sha in r.get("branch_shas", {}).items():
        now = _git("rev-parse", "--verify", branch, check=False).stdout.strip()
        if now and now != sha:
            refusals.append(f"{branch} moved after its test ({sha[:10]} -> {now[:10]}); resubmit")
    merged = _git("rev-parse", "--verify", REF_PREFIX + jid, check=False).stdout.strip()
    if merged != r["merged_sha"]:
        refusals.append(f"{REF_PREFIX}{jid} missing or not the tested merge")
    head = _git("symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
    if head == CFG.base and not refusals:
        # Local edits in the main checkout are fine unless the landing touches the same files
        # (git's own --ff-only rule); refuse up front so nothing is half-applied.
        dirty = set(_git("diff", "--name-only", "HEAD", check=False).stdout.split())
        landing = set(
            _git("diff", "--name-only", r["base_sha"], r["merged_sha"], check=False).stdout.split()
        )
        if dirty & landing:
            refusals.append(
                f"{CFG.repo} has local changes to files this lands: {sorted(dirty & landing)[:10]}"
            )
    if refusals:
        for line in refusals:
            print(f"refused: {line}", file=sys.stderr)
        return 4
    if head == CFG.base:
        _git("merge", "--ff-only", r["merged_sha"])
    else:
        _git("update-ref", f"refs/heads/{CFG.base}", r["merged_sha"], r["base_sha"])
    _git("update-ref", "-d", REF_PREFIX + jid, check=False)
    r["landed"] = _now()
    path.write_text(json.dumps(r, indent=2), encoding="utf-8")
    print(
        f"landed {jid}: {CFG.base} {r['base_sha'][:10]} -> {r['merged_sha'][:10]} ({' + '.join(_branches(r))})"
    )
    return 0


def _kill_runner(pid_text: str) -> str | None:
    """Kill the runner a pid file names, if it is still that process. Returns why it did not
    (stale file, reused pid, unreadable or unverifiable file), or None after the kill.

    The file survives a reboot, and Windows reuses pids, so the pid alone proves nothing: the
    process must also have the creation time recorded when the runner started.
    """
    parts = pid_text.split(None, 1)
    if not parts or not parts[0].isdigit():
        return f"pid file is unreadable ({pid_text.strip()[:40]!r})"
    pid, recorded = int(parts[0]), (parts[1].strip() if len(parts) > 1 else "")
    current = _proc_start(pid)
    if current is None:
        return f"stale pid file: runner {pid} is no longer running"
    if not recorded:
        return f"pid file for {pid} has no creation time to check it against (older runner)"
    if current != recorded:
        return f"stale pid file: pid {pid} now belongs to a different process"
    # Killing the runner closes its job handles, which kills each stage's tree too.
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, 9)
    return None


def cmd_cancel(args: argparse.Namespace) -> int:
    queue, running, done, _logs, cand_root, _jobs, _procs = CFG.dirs()
    jid = args.id
    _git("update-ref", "-d", REF_PREFIX + jid, check=False)
    done.mkdir(parents=True, exist_ok=True)
    for p in sorted(queue.glob(f"*-{jid}.json")) if queue.exists() else []:
        p.replace(done / f"{jid}.cancelled.job.json")
        print(f"cancelled queued {p.name}")
        return 0
    jobs = sorted(running.glob(f"*-{jid}.json")) if running.exists() else []
    if not jobs:
        print(f"no queued or running job {jid}", file=sys.stderr)
        return 4
    pid_file = running / f"{jid}.pid"
    if pid_file.exists():
        why = _kill_runner(pid_file.read_text(encoding="utf-8"))
        if why:
            print(f"{why}; nothing killed", file=sys.stderr)
        pid_file.unlink(missing_ok=True)
    for entry in _procs_dir().glob(f"{jid}-*.json") if _procs_dir().exists() else []:
        _terminate_job(entry.stem)
        entry.unlink(missing_ok=True)
    cand = cand_root / jid
    _git("worktree", "remove", "--force", str(cand), check=False)
    shutil.rmtree(cand, ignore_errors=True)
    _git("worktree", "prune", check=False)
    jobs[0].replace(done / f"{jid}.cancelled.job.json")
    print(f"cancelled running {jobs[0].name}")
    return 0


def _lock_is_free() -> bool:
    probe = HeavyLock("probe")
    if probe.try_acquire():
        fh, probe.fh = probe.fh, None
        if fh is not None:
            fh.close()  # closing drops the lock without touching the owner label
        return True
    return False


def cmd_status(_args: argparse.Namespace) -> int:
    queue, running, done, *_ = CFG.dirs()
    for label, folder in (("queued", queue), ("running", running)):
        for p in sorted(folder.glob("*.json")) if folder.exists() else []:
            job = json.loads(p.read_text(encoding="utf-8"))
            print(f"{label:8} {job['id']:20} {' + '.join(_branches(job))}")
    results = (
        [p for p in done.glob("*.json") if not p.name.endswith(".job.json")]
        if done.exists()
        else []
    )
    for p in sorted(results, key=lambda q: q.stat().st_mtime):
        r = json.loads(p.read_text(encoding="utf-8"))
        total = sum(s["seconds"] for s in r.get("stages_run", []))
        state = "landed" if r.get("landed") else (r.get("status") or "")
        print(
            f"done     {r['id']:20} {state:8} {r.get('failed_stage') or '':10} {total:7.0f}s {r.get('finished')}"
        )
    print(f"lock     {'free' if _lock_is_free() else 'held by ' + lock_owner()}")
    return 0


# --------------------------------------------------------------------------- run / ps / reap / lock


def cmd_run(args: argparse.Namespace) -> int:
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        print("run: no command", file=sys.stderr)
        return 2
    name = f"{args.name or 'run'}-{os.getpid()}"  # unique; `reap --name` matches by prefix
    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    if not cwd.is_dir():
        print(f"run: --cwd {args.cwd} is not a directory", file=sys.stderr)
        return 2
    lock = HeavyLock(f"run {name} ({' '.join(cmd)[:80]})")
    if args.heavy and not lock.acquire(CFG.lock_wait):
        print(f"mergeq: heavy lock wait expired (held by {lock_owner()})", file=sys.stderr)
        return 125
    slot = TargetedSlot()
    if not args.heavy and not slot.acquire(CFG.targeted_wait):
        print(
            f"mergeq: no targeted slot after {CFG.targeted_wait}s; nothing ran, try again",
            file=sys.stderr,
        )
        return 125
    try:
        rc, secs, timed_out, peak = run_group(
            cmd,
            name=name,
            cwd=cwd,
            timeout=args.timeout,
            env={**os.environ, IN_SLOT_ENV: "1"},
            heavy=args.heavy,
        )
    finally:
        slot.release()
        lock.release()
    if timed_out:
        print(
            f"mergeq: '{' '.join(cmd)}' timed out after {args.timeout}s; process tree killed",
            file=sys.stderr,
        )
    elif peak:
        print(f"mergeq: done in {secs}s, peak memory {peak} MB", file=sys.stderr)
    return rc


def _managed() -> list[dict]:
    d = _procs_dir()
    out = []
    for entry in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            info = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not _pid_alive(int(info.get("pid", 0))):
            entry.unlink(missing_ok=True)  # its runner died; kill-on-close took the tree
            continue
        job = _job_info(info["name"])
        info["pids"], info["peak_mb"] = job if job else ([info.get("child_pid")], 0)
        out.append(info)
    return out


def _system_processes() -> list[dict]:
    names = CFG.ps.get("names", ["python.exe"])
    if IS_WINDOWS:
        flt = " or ".join(f"Name='{n}'" for n in names)
        ps = (
            f'Get-CimInstance Win32_Process -Filter "{flt}" | '
            "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps], text=True, capture_output=True
        ).stdout
        data = json.loads(out) if out.strip() else []
        data = data if isinstance(data, list) else [data]
        return [
            {
                "pid": d["ProcessId"],
                "ppid": d["ParentProcessId"],
                "name": d["Name"],
                "cmd": d.get("CommandLine") or "",
            }
            for d in data
        ]
    out = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,comm=,args="], text=True, capture_output=True
    ).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and any(parts[2].startswith(n.split(".")[0]) for n in names):
            rows.append(
                {"pid": int(parts[0]), "ppid": int(parts[1]), "name": parts[2], "cmd": parts[3]}
            )
    return rows


def _unmanaged(match: str | None) -> list[dict]:
    managed = {int(p) for info in _managed() for p in info["pids"] if p}
    ignore = [re.compile(p, re.I) for p in CFG.ps.get("ignore", [])]
    me = {os.getpid(), os.getppid()}
    rows = []
    for row in _system_processes():
        if row["pid"] in managed or row["pid"] in me or any(r.search(row["cmd"]) for r in ignore):
            continue
        if match and not re.search(match, row["cmd"], re.I):
            continue
        rows.append(row)
    return rows


def cmd_ps(args: argparse.Namespace) -> int:
    print(f"lock: {'free' if _lock_is_free() else 'held by ' + lock_owner()}")
    managed = _managed()
    for info in managed:
        flag = "HEAVY" if info.get("heavy") else "     "
        print(
            f"{flag} {info['name']:28} runner={info['pid']:<6} procs={len(info['pids']):<3} "
            f"peak={info['peak_mb']}MB since={info['started']} cwd={info['cwd']}\n      {' '.join(info['cmd'])[:150]}"
        )
    if not managed:
        print("no mergeq-managed process groups")
    if args.all:
        rows = _unmanaged(None)
        print(f"\nunmanaged ({len(rows)}):")
        for row in rows:
            print(
                f"  pid={row['pid']:<6} ppid={row['ppid']:<6} {row['name']:12} {row['cmd'][:150]}"
            )
    return 0


def cmd_reap(args: argparse.Namespace) -> int:
    if args.name:
        names = [
            e.stem for e in sorted(_procs_dir().glob("*.json")) if e.stem.startswith(args.name)
        ]
        killed = [n for n in names if _terminate_job(n)]
        print(f"killed: {', '.join(killed)}" if killed else f"no group named {args.name}*")
        return 0 if killed else 4
    rows = _unmanaged(
        args.match or re.escape(str(CFG.worktree_root)) + "|" + re.escape(str(CFG.repo))
    )
    for row in rows:
        print(f"{'would kill' if args.dry_run else 'killing'} pid={row['pid']} {row['cmd'][:150]}")
        if not args.dry_run:
            if IS_WINDOWS:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(row["pid"])], capture_output=True
                )
            else:
                os.kill(row["pid"], 9)
    if not rows:
        print("nothing to reap")
    return 0


def cmd_lock(_args: argparse.Namespace) -> int:
    if _lock_is_free():
        print(f"free ({CFG.lock_file})")
    else:
        print(f"held by {lock_owner()} ({CFG.lock_file})")
    if CFG.targeted_slots > 0:
        print(f"targeted slots: {_slots_in_use()} of {CFG.targeted_slots} in use")
    return 0


# --------------------------------------------------------------------------- worktrees, notes


def _worktrees() -> list[dict]:
    out = _git("worktree", "list", "--porcelain").stdout
    rows, cur = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                rows.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = Path(line[9:]).resolve()
        elif line.startswith("branch "):
            cur["branch"] = line[7:].removeprefix("refs/heads/")
    return rows


def cmd_worktree(args: argparse.Namespace) -> int:
    if args.action == "list":
        for wt in _worktrees():
            path = wt["path"]
            if path.parent != CFG.worktree_root:
                continue
            branch = wt.get("branch", "(detached)")
            counts = _git(
                "rev-list", "--left-right", "--count", f"{CFG.base}...{branch}", check=False
            ).stdout.split()
            behind, ahead = (counts + ["?", "?"])[:2]
            dirty = len(_git("status", "--porcelain", cwd=path, check=False).stdout.splitlines())
            landed = (
                _git("merge-base", "--is-ancestor", branch, CFG.base, check=False).returncode == 0
            )
            print(
                f"{path.name:16} {branch:24} +{ahead}/-{behind} dirty={dirty:<3} {'landed' if landed else ''}"
            )
        return 0
    if not args.name:
        print("worktree: NAME required", file=sys.stderr)
        return 2
    path = CFG.worktree_root / args.name
    branch = CFG.branch_prefix + args.name
    if args.action == "new":
        exists = _git("rev-parse", "--verify", f"refs/heads/{branch}", check=False).returncode == 0
        cmd = (
            ["worktree", "add", str(path), branch]
            if exists
            else ["worktree", "add", "-b", branch, str(path), args.base or CFG.base]
        )
        r = _git(*cmd, check=False)
        if r.returncode != 0:
            print(r.stderr.strip(), file=sys.stderr)
            return 4
        print(f"{path}  ({branch}{' existing' if exists else ' from ' + (args.base or CFG.base)})")
        return 0
    # rm
    landed = _git("merge-base", "--is-ancestor", branch, CFG.base, check=False).returncode == 0
    dirty = path.exists() and bool(
        _git("status", "--porcelain", cwd=path, check=False).stdout.strip()
    )
    if not args.force and (not landed or dirty):
        why = "has uncommitted changes" if dirty else f"is not in {CFG.base}"
        print(f"refused: {branch} {why}; use --force to discard", file=sys.stderr)
        return 4
    _git("worktree", "remove", *(["--force"] if args.force else []), str(path), check=False)
    _git("branch", "-D" if args.force else "-d", branch, check=False)
    _git("worktree", "prune", check=False)
    print(f"removed {path} and {branch}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    d = CFG.home / "jobs" / args.id
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{args.kind.upper()}.md"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## {args.kind} {_now()}\n\n{text.strip()}\n")
    print(path)
    return 0


# --------------------------------------------------------------------------- main


def main() -> int:
    global CFG
    CFG = Config()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--id", required=True)
    s.add_argument(
        "--branch", required=True, action="append", help="repeat for a train; merged in order"
    )
    s.add_argument("--stages", help="comma list of stages or presets from mergeq.toml")
    s.add_argument("--note")
    sub.add_parser("next")
    sub.add_parser("status")
    for name in ("cancel", "land"):
        sub.add_parser(name).add_argument("--id", required=True)
    r = sub.add_parser("run")
    r.add_argument(
        "--heavy", action="store_true", help="hold the machine-wide heavy lock while it runs"
    )
    r.add_argument("--timeout", type=int, default=None)
    r.add_argument("--name")
    r.add_argument("--cwd", help="run CMD in this directory (default: the current one)")
    r.add_argument("cmd", nargs=argparse.REMAINDER)
    p = sub.add_parser("ps")
    p.add_argument(
        "--all", action="store_true", help="also list matching processes mergeq did not start"
    )
    k = sub.add_parser("reap")
    g = k.add_mutually_exclusive_group(required=True)
    g.add_argument("--name", help="kill one mergeq-managed group")
    g.add_argument(
        "--unmanaged", action="store_true", help="kill unmanaged processes under the repo/worktrees"
    )
    k.add_argument("--match", help="regex on the command line (with --unmanaged)")
    k.add_argument("--dry-run", action="store_true")
    lk = sub.add_parser("lock")
    lk.add_argument("action", choices=["status"])
    w = sub.add_parser("worktree")
    w.add_argument("action", choices=["new", "rm", "list"])
    w.add_argument("name", nargs="?")
    w.add_argument("--base")
    w.add_argument("--force", action="store_true")
    n = sub.add_parser("note")
    n.add_argument("--id", required=True)
    n.add_argument("--kind", required=True, choices=["handoff", "review", "ledger"])
    n.add_argument("--file")
    args = ap.parse_args()
    handlers = {
        "submit": cmd_submit,
        "next": cmd_next,
        "status": cmd_status,
        "cancel": cmd_cancel,
        "land": cmd_land,
        "run": cmd_run,
        "ps": cmd_ps,
        "reap": cmd_reap,
        "lock": cmd_lock,
        "worktree": cmd_worktree,
        "note": cmd_note,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
