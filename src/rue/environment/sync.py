"""Subprocess transfer state for `Environment` resources.

`EnvironmentSyncState` is a plain dataclass that implements the
`rue.resources.sync.SyncState` protocol structurally. Virtual ABC
registration happens in `rue.resources.builtins` to avoid a module-load
cycle between `rue.environment` and `rue.resources`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from rue.environment.checkpoint import FileEntry


@dataclass(frozen=True, slots=True)
class EnvironmentSyncState:
    """Subprocess-safe object state for an `Environment` resource."""

    root: Path
    baseline_manifest: tuple[FileEntry, ...] | None = None
    overrides: dict[str, str] = field(default_factory=dict)
    hidden: frozenset[str] = frozenset()
    cwd: PurePosixPath = field(default_factory=lambda: PurePosixPath("."))

    def apply_transfer(self) -> None:
        """No-op: env state from a worker has no parent env to merge into.

        Test-scope environments materialize and tear down inside the worker;
        when their state lands in the parent for an unmatched spec, there
        is nothing to write back.
        """


__all__ = [
    "EnvironmentSyncState",
]
