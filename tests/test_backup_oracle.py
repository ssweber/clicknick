"""Random backup/restore sequences: no tree is lost while fewer than 5 newer ones are kept.

Each step edits ``src/plc``, regenerates it (the build's backup), runs
``backup``, ``restore`` or ``restore <time>``, sometimes with a failure
injected: a copy into ``src/plc`` or ``backup/src/plc`` fails, the move of a
backup to or from ``backup/older`` fails, the backup time cannot be written, or
a prune delete stops part way. After every step:

- an operation that succeeded left the edits ``src/plc`` held when it began
  as the newest backup, or in ``src/plc`` as the backup it restored;
- an operation that failed left ``src/plc`` as it began;
- every tree that was ever in a backup, or in ``src/plc`` with edits when an
  operation began, is still in ``src/plc`` or a backup, unless at least
  ``KEPT_PLC_BACKUPS`` distinct trees that were the newest backup later than
  it are kept;
- every listed backup is a whole tree that was once written;
- a restore's ``restored_from`` exists and holds what ``src/plc`` now holds.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import shutil
from pathlib import Path

import pytest

from clicknick.services import project_workspace
from clicknick.services.project_workspace import (
    KEPT_PLC_BACKUPS,
    backup_modified_plc_source,
    backup_plc_source,
    older_plc_backups,
    older_plc_backups_dir,
    plc_backup_dir,
    plc_source_dir,
    record_generated_plc_source,
    restore_plc_source,
)

Tree = frozenset[tuple[str, str]]

_FIXED_SEEDS = range(20)
_FIXED_STEPS = 30
# Kept small for the gate; set CLICKNICK_ORACLE_SEEDS=200 (and CLICKNICK_ORACLE_STEPS) for a deeper run.
_RANDOM_SEEDS = int(os.environ.get("CLICKNICK_ORACLE_SEEDS", "20"))
_RANDOM_STEPS = int(os.environ.get("CLICKNICK_ORACLE_STEPS", "15"))


class _Injected(OSError):
    pass


def _read(root: Path) -> Tree | None:
    if not root.is_dir():
        return None
    return frozenset(
        (path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
        for path in root.rglob("*")
        if path.is_file()
    )


class _Run:
    def _now(self) -> dt.datetime:
        self.clock += dt.timedelta(minutes=1)
        return self.clock

    def __init__(self, project: Path, rng: random.Random, monkeypatch) -> None:
        self.project = project
        self.rng = rng
        self.monkeypatch = monkeypatch
        self.step = 0
        self.made = 0
        self.written: set[Tree] = set()  # every tree ever written to src/plc
        self.edited: list[Tree] = []  # edited trees, to write one again
        self.generated: Tree | None = None
        self.tracked: set[Tree] = set()  # trees that must not be lost early
        self.began: Tree | None = None  # src/plc as the operation began
        self.pending: Tree | None = None  # edited src/plc as the operation began
        self.newest_at: dict[Tree, int] = {}  # last step a tree was the newest backup
        self.clock = dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC)
        monkeypatch.setattr(project_workspace, "_now", self._now)

    @property
    def source(self) -> Path:
        return plc_source_dir(self.project)

    def _new_tree(self, kind: str) -> Tree:
        self.made += 1
        tree = {("main.py", f"{kind} {self.made}\n")}
        if self.rng.random() < 0.5:
            tree.add(("extra.py", f"helper {self.made}\n"))
        return frozenset(tree)

    def _write(self, tree: Tree) -> None:
        """Write *tree* to src/plc, its files dated by the run's clock."""
        if self.source.exists():
            shutil.rmtree(self.source)
        self.source.mkdir(parents=True)
        stamp = self.clock.timestamp()
        for name, text in tree:
            path = self.source / name
            path.write_text(text, encoding="utf-8")
            os.utime(path, (stamp, stamp))
        self.written.add(tree)

    def kept(self) -> dict[str, Tree]:
        """Each listed backup by where it is: "newest" or an older backup's name."""
        backups: dict[str, Tree] = {}
        newest = _read(plc_backup_dir(self.project))
        if newest is not None:
            backups["newest"] = newest
        root = older_plc_backups_dir(self.project)
        for name in older_plc_backups(self.project):
            tree = _read(root / name / "src" / "plc")
            assert tree is not None
            backups[name] = tree
        return backups

    # Steps --------------------------------------------------------------

    def edit(self) -> str:
        if self.edited and self.rng.random() < 0.3:
            tree = self.rng.choice(self.edited)  # the same edits again
        else:
            tree = self._new_tree("edits")
            self.edited.append(tree)
        self._write(tree)
        return "edit"

    def _begin(self) -> None:
        """An operation starts: edited source in src/plc must survive it.

        An operation that fails leaves src/plc as it was, so an edit made after
        it may drop that tree.
        """
        self.began = _read(self.source)
        tree = self.began
        self.pending = tree if tree is not None and tree != self.generated else None

    def _failed(self, injected: str | None, history: str) -> str:
        assert injected in ("copy", "move"), history
        assert _read(self.source) == self.began, f"{history}: src/plc changed"
        self.pending = None
        return history

    def regenerate(self) -> str:
        self._begin()
        backup_modified_plc_source(self.project)
        tree = self._new_tree("generated")
        self._write(tree)
        record_generated_plc_source(self.project)
        self.generated = tree
        return "regenerate"

    def _inject(self, patch, *, copies_into: tuple[Path, ...]) -> str | None:
        roll = self.rng.random()
        if roll < 0.10:
            into = self.rng.choice(copies_into)
            replace_tree = project_workspace._replace_tree

            def failing_copy(source: Path, destination: Path) -> int:
                if destination == into:
                    raise _Injected("copy failed")
                return replace_tree(source, destination)

            patch.setattr(project_workspace, "_replace_tree", failing_copy)
            return "copy"
        if roll < 0.26:
            newest = plc_backup_dir(self.project)
            older_root = older_plc_backups_dir(self.project)
            replace = Path.replace
            moves = roll < 0.18
            failed: list[Path] = []

            def failing_replace(path: Path, target) -> Path:
                target = Path(target)
                if moves:
                    # A backup moving to or from backup/older; the move back works.
                    hit = not failed and newest in (path, target)
                    hit = hit and older_root in (*path.parents, *target.parents)
                else:
                    hit = path.name == "backup-time.txt.staging"
                if hit:
                    failed.append(path)
                    raise _Injected("move failed")
                return replace(path, target)

            patch.setattr(Path, "replace", failing_replace)
            return "move" if moves else "time file"
        if roll < 0.36:
            rmtree = shutil.rmtree

            def part_way(path, *args, **kwargs):
                path = Path(path)
                if not path.name.startswith(".pruning-"):
                    return rmtree(path, *args, **kwargs)
                for file in path.rglob("main.py"):
                    file.unlink()
                return None  # and stops

            patch.setattr(project_workspace.shutil, "rmtree", part_way)
            return "prune stops part way"
        return None

    def backup(self) -> str:
        self._begin()
        with self.monkeypatch.context() as patch:
            injected = self._inject(patch, copies_into=(plc_backup_dir(self.project),))
            try:
                backup_plc_source(self.project)
            except _Injected:
                return self._failed(injected, f"backup ({injected} failed)")
        return f"backup{f' ({injected})' if injected else ''}"

    def restore(self, older: bool) -> str:
        names = older_plc_backups(self.project)
        if (older and not names) or not plc_backup_dir(self.project).is_dir():
            return self.edit()
        name = self.rng.choice(names) if older else None
        self._begin()
        with self.monkeypatch.context() as patch:
            # The copy of the chosen backup into src/plc, or the backup of the edits.
            copies_into = (self.source, plc_backup_dir(self.project))
            injected = self._inject(patch, copies_into=copies_into)
            try:
                restored = restore_plc_source(self.project, name)
            except _Injected:
                return self._failed(injected, f"restore {name or ''} ({injected} failed)")
        assert restored.restored_from.is_dir(), restored
        assert _read(restored.restored_from) == _read(self.source)
        return f"restore {name or ''}{f' ({injected})' if injected else ''}"

    # Checks -------------------------------------------------------------

    def check(self, history: list[str]) -> None:
        kept = self.kept()
        for where, tree in kept.items():
            assert tree in self.written, (where, tree, history)
        source = _read(self.source)
        newest = kept.get("newest")
        if self.pending is not None:
            # The edits are the newest backup now, or src/plc holds them as the
            # backup it restored (which keeps the step it was last the newest at).
            restored = self.pending == source and self.pending in kept.values()
            assert self.pending == newest or restored, (
                f"edits {sorted(self.pending)} were not backed up",
                history,
            )
            self.tracked.add(self.pending)
            self.pending = None
        self.tracked.update(kept.values())
        if newest is not None:
            self.newest_at[newest] = self.step
        present = set(kept.values())
        if source is not None:
            present.add(source)
        backed_up = set(kept.values())
        for tree in self.tracked - present:
            since = self.newest_at.get(tree, -1)
            newer = {
                kept_tree for kept_tree in backed_up if self.newest_at.get(kept_tree, -1) > since
            }
            assert len(newer) >= KEPT_PLC_BACKUPS, (
                f"lost {sorted(tree)} with {len(newer)} newer backups kept",
                history,
            )

    def play(self, steps: int) -> None:
        moves = (
            (self.edit, 3),
            (self.regenerate, 2),
            (self.backup, 2),
            (lambda: self.restore(older=False), 2),
            (lambda: self.restore(older=True), 2),
        )
        actions = [action for action, weight in moves for _ in range(weight)]
        history: list[str] = []
        self.regenerate()
        for self.step in range(1, steps + 1):
            history.append(self.rng.choice(actions)())
            self.check(history)


def _play(tmp_path: Path, seed: int, monkeypatch, steps: int) -> None:
    project = tmp_path / f"seed-{seed}"
    with monkeypatch.context() as patch:
        _Run(project, random.Random(seed), patch).play(steps)


@pytest.mark.parametrize("seed", _FIXED_SEEDS)
def test_no_backup_is_lost_while_fewer_than_five_newer_are_kept(
    tmp_path: Path, monkeypatch, seed: int
) -> None:
    _play(tmp_path, seed, monkeypatch, _FIXED_STEPS)


def test_no_backup_is_lost_on_random_seeds(tmp_path: Path, monkeypatch) -> None:
    seeds = random.SystemRandom().sample(range(10**6, 10**7), _RANDOM_SEEDS)
    for seed in seeds:
        try:
            _play(tmp_path, seed, monkeypatch, _RANDOM_STEPS)
        except AssertionError as error:
            raise AssertionError(f"seed {seed}: {error}") from error
