"""Subprocess transfer state for `Environment` resources.

`EnvironmentSyncState` is a plain dataclass that implements the
`rue.resources.sync.SyncState` protocol structurally. Virtual ABC
registration happens in `rue.resources.builtins` to avoid a module-load
cycle between `rue.environment` and `rue.resources`.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path, PurePosixPath

from rue.environment.snapshot import FileEntry


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

    @classmethod
    def from_path(
        cls, root: Path, path: PurePosixPath, kind: FileDeltaKind
    ) -> FileDelta:
        """Capture metadata and payload for a path under ``root``."""
        absolute = root / path
        stat_result = os.lstat(absolute)
        mode = stat.S_IMODE(stat_result.st_mode)
        mtime_ns = stat_result.st_mtime_ns
        if stat.S_ISLNK(stat_result.st_mode):
            return cls(
                path=path,
                kind=kind,
                symlink_target=os.readlink(absolute),
                mode=mode,
                mtime_ns=mtime_ns,
            )
        return cls(
            path=path,
            kind=kind,
            content=absolute.read_bytes(),
            mode=mode,
            mtime_ns=mtime_ns,
        )


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


__all__ = [
    "EnvironmentSyncState",
    "FileDelta",
    "FileDeltaKind",
]
