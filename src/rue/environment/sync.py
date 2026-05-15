"""Subprocess transfer state for `Environment` resources.

`EnvironmentSyncState` is a plain dataclass that implements the
`rue.resources.sync.SyncState` protocol structurally. Virtual ABC
registration happens in `rue.environment.builtin` to avoid a module-load
cycle between `rue.environment` and `rue.resources`.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path, PurePosixPath

from rue.environment.snapshot import (
    FileEntry,
    Snapshot,
    diff_snapshots,
    scan_snapshot,
)


class FileDeltaKind(StrEnum):
    """The kind of change a `FileDelta` describes."""

    ADDED = auto()
    MODIFIED = auto()
    DELETED = auto()


@dataclass(frozen=True, slots=True)
class FileDelta:
    """A single file change carried in a worker→parent sync update."""

    path: PurePosixPath
    kind: FileDeltaKind
    content: bytes | None = None
    symlink_target: str | None = None
    mode: int = 0o644
    mtime_ns: int = 0


@dataclass(frozen=True, slots=True)
class EnvironmentSyncState:
    """Subprocess-safe snapshot of an `Environment` resource."""

    parent_root: Path
    baseline_manifest: tuple[FileEntry, ...]
    overrides: dict[str, str] = field(default_factory=dict)
    hidden: frozenset[str] = frozenset()
    cwd: PurePosixPath = field(default_factory=lambda: PurePosixPath("."))
    scope_value: str = ""
    deltas: tuple[FileDelta, ...] = ()

    def apply_transfer(self) -> None:
        """No-op: env state from a worker has no parent env to merge into.

        Test-scope environments materialize and tear down inside the worker;
        when their state lands in the parent for an unmatched spec, there
        is nothing to write back.
        """


def manifest_to_snapshot(
    root: Path,
    manifest: tuple[FileEntry, ...],
) -> Snapshot:
    """Wrap a manifest tuple in a `Snapshot` keyed by path."""
    return Snapshot(
        root=root,
        entries={entry.path: entry for entry in manifest},
    )


def compute_deltas(
    *,
    baseline: Snapshot,
    current_root: Path,
) -> tuple[FileDelta, ...]:
    """Diff `current_root` against `baseline` and capture file content."""
    current = scan_snapshot(current_root)
    diff = diff_snapshots(baseline, current)
    deltas: list[FileDelta] = []

    for path in diff.added:
        deltas.append(_capture_delta(current_root, path, FileDeltaKind.ADDED))
    for path in diff.modified:
        deltas.append(
            _capture_delta(current_root, path, FileDeltaKind.MODIFIED)
        )
    for path in diff.deleted:
        deltas.append(FileDelta(path=path, kind=FileDeltaKind.DELETED))
    return tuple(deltas)


def apply_deltas(*, root: Path, deltas: tuple[FileDelta, ...]) -> None:
    """Apply worker-emitted deltas to a parent environment root."""
    for delta in deltas:
        target = root / delta.path
        match delta.kind:
            case FileDeltaKind.DELETED:
                if target.is_symlink() or target.exists():
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
            case FileDeltaKind.ADDED | FileDeltaKind.MODIFIED:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink() or target.exists():
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                if delta.symlink_target is not None:
                    os.symlink(delta.symlink_target, target)
                    continue
                payload = delta.content or b""
                target.write_bytes(payload)
                os.chmod(target, delta.mode)


def _capture_delta(
    root: Path, path: PurePosixPath, kind: FileDeltaKind
) -> FileDelta:
    absolute = root / path
    stat_result = os.lstat(absolute)
    mode = stat.S_IMODE(stat_result.st_mode)
    mtime_ns = stat_result.st_mtime_ns
    if stat.S_ISLNK(stat_result.st_mode):
        return FileDelta(
            path=path,
            kind=kind,
            symlink_target=os.readlink(absolute),
            mode=mode,
            mtime_ns=mtime_ns,
        )
    return FileDelta(
        path=path,
        kind=kind,
        content=absolute.read_bytes(),
        mode=mode,
        mtime_ns=mtime_ns,
    )


__all__ = [
    "EnvironmentSyncState",
    "FileDelta",
    "FileDeltaKind",
    "apply_deltas",
    "compute_deltas",
    "manifest_to_snapshot",
]
