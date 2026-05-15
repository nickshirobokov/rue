"""On-disk layout, reflink-aware tree clones, and stale-suite GC."""

from __future__ import annotations

import fcntl
import os
import platform
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from uuid import UUID

from rue.context.models import ScopeOwner
from rue.context.scopes import CurrentProcessKind


class _CloneStrategy(StrEnum):
    """How `_clone_tree` materializes a directory."""

    APFS_CLONEFILE = auto()
    LINUX_REFLINK = auto()
    SHUTIL_COPYTREE = auto()


def _detect_clone_strategy() -> _CloneStrategy:
    """Probe `cp` once at import time to pick the cheapest clone strategy."""
    if not shutil.which("cp"):
        return _CloneStrategy.SHUTIL_COPYTREE

    system = platform.system()
    with tempfile.TemporaryDirectory(prefix="rue-clone-probe-") as tmp:
        src = Path(tmp, "src")
        dst = Path(tmp, "dst")
        src.write_text("probe")
        if system == "Darwin":
            outcome = subprocess.run(
                ["cp", "-c", str(src), str(dst)],
                capture_output=True,
                check=False,
            )
            if outcome.returncode == 0:
                return _CloneStrategy.APFS_CLONEFILE
        elif system == "Linux":
            outcome = subprocess.run(
                ["cp", "--reflink=auto", str(src), str(dst)],
                capture_output=True,
                check=False,
            )
            if outcome.returncode == 0:
                return _CloneStrategy.LINUX_REFLINK
    return _CloneStrategy.SHUTIL_COPYTREE


_CLONE_STRATEGY = _detect_clone_strategy()


def clone_tree(src: Path, dst: Path) -> None:
    """Materialize `src` at `dst`, using O(1) reflinks when available.

    `dst` must not already exist (clonefile/reflink semantics require a
    fresh destination). Symlinks are preserved as symlinks.
    """
    if dst.exists():
        msg = f"clone_tree destination already exists: {dst}"
        raise FileExistsError(msg)
    dst.parent.mkdir(parents=True, exist_ok=True)

    match _CLONE_STRATEGY:
        case _CloneStrategy.APFS_CLONEFILE:
            subprocess.run(
                ["cp", "-c", "-R", str(src), str(dst)],
                check=True,
                capture_output=True,
            )
        case _CloneStrategy.LINUX_REFLINK:
            subprocess.run(
                ["cp", "--reflink=auto", "-r", str(src), str(dst)],
                check=True,
                capture_output=True,
            )
        case _CloneStrategy.SHUTIL_COPYTREE:
            shutil.copytree(src, dst, symlinks=True)


def empty_tree(path: Path) -> None:
    """Create an empty directory at `path`. Removes any existing file/dir."""
    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    path.mkdir(parents=True)


@dataclass(frozen=True, slots=True)
class _SuiteLock:
    """An open `fcntl` lock for the lifetime of one suite run directory."""

    suite_dir: Path
    file_handle: int


class EnvironmentStorage:
    """Owner of the `.rue/environment-{run,cache}/` layout.

    Allocation is cheap (single mkdir) so workers can re-run the factory.
    The suite lock is held for the suite's lifetime, granting `gc_stale()`
    a race-free way to detect dead suites.
    """

    _RUN_DIRNAME = "environment-run"
    _CACHE_DIRNAME = "environment-cache"
    _LOCK_FILENAME = "lock"

    _suite_locks: dict[Path, _SuiteLock] = {}
    _suite_locks_guard = threading.Lock()

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or Path.cwd()) / ".rue"

    @property
    def run_dir(self) -> Path:
        """Root for per-suite run directories."""
        return self.base_dir / self._RUN_DIRNAME

    @property
    def cache_dir(self) -> Path:
        """Root for content-addressed source materializations."""
        return self.base_dir / self._CACHE_DIRNAME

    def suite_dir(self, suite_id: UUID) -> Path:
        """Root for one suite execution."""
        return self.run_dir / str(suite_id)

    def allocate(
        self,
        suite_id: UUID,
        owner: ScopeOwner,
        *,
        process_kind: CurrentProcessKind = CurrentProcessKind.MAIN,
    ) -> Path:
        """Return a new on-disk root for an environment.

        The root is canonical for the logical scope owner, so parent and
        worker processes see the same real files. Only the parent (`MAIN`)
        holds the suite lock; workers skip it because the parent already does.
        """
        if process_kind is CurrentProcessKind.MAIN:
            self._ensure_suite_lock(suite_id)
        scope_dir = self.suite_dir(suite_id) / owner.scope.value
        scope_dir.mkdir(parents=True, exist_ok=True)
        env_root = scope_dir / owner.key
        env_root.mkdir(parents=True, exist_ok=True)
        return env_root

    def release(self, root: Path) -> None:
        """Tear down an env root if it exists."""
        shutil.rmtree(root, ignore_errors=True)

    def gc_stale(self) -> list[Path]:
        """Remove `environment-run/<uuid>/` dirs whose owning process is gone.

        A suite dir is considered dead when its `lock` file can be acquired
        with `fcntl.flock(LOCK_EX | LOCK_NB)` from this process. Dirs locked
        by this process are never removed.
        """
        if not self.run_dir.exists():
            return []
        held_paths = {lock.suite_dir for lock in self._suite_locks.values()}
        removed: list[Path] = []
        for child in self.run_dir.iterdir():
            if not child.is_dir():
                continue
            if child in held_paths:
                continue
            lock_path = child / self._LOCK_FILENAME
            if not lock_path.exists():
                shutil.rmtree(child, ignore_errors=True)
                removed.append(child)
                continue
            try:
                handle = os.open(lock_path, os.O_RDWR)
            except OSError:
                continue
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(handle)
                continue
            try:
                shutil.rmtree(child, ignore_errors=True)
                removed.append(child)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
                os.close(handle)
        return removed

    def _ensure_suite_lock(self, suite_id: UUID) -> None:
        suite_dir = self.suite_dir(suite_id)
        with self._suite_locks_guard:
            if suite_dir in self._suite_locks:
                return
            suite_dir.mkdir(parents=True, exist_ok=True)
            lock_path = suite_dir / self._LOCK_FILENAME
            handle = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(handle)
                msg = (
                    f"Suite {suite_id} environment dir is already locked by "
                    "another process."
                )
                raise RuntimeError(msg) from None
            self._suite_locks[suite_dir] = _SuiteLock(
                suite_dir=suite_dir, file_handle=handle
            )

    @classmethod
    def release_suite(
        cls,
        suite_id: UUID,
        base_dir: Path | None = None,
    ) -> None:
        """Release the lock for a suite and remove the run directory."""
        run_dir = (base_dir or Path.cwd()) / ".rue" / cls._RUN_DIRNAME
        suite_dir = run_dir / str(suite_id)
        with cls._suite_locks_guard:
            lock = cls._suite_locks.pop(suite_dir, None)
        if lock is not None:
            try:
                fcntl.flock(lock.file_handle, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(lock.file_handle)
        shutil.rmtree(suite_dir, ignore_errors=True)


__all__ = [
    "EnvironmentStorage",
    "clone_tree",
    "empty_tree",
]
