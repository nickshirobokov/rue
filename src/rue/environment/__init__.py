"""Rue Environment resource: filesystem + env-var sandbox for tests."""

from __future__ import annotations

from rue.environment import sources
from rue.environment.checkpoint import (
    Checkpoint,
    Deletion,
    Diff,
    FileDelta,
    FileDiff,
    FileState,
    PathDelta,
    PathNotInDiff,
    PathState,
    SymlinkDelta,
    SymlinkState,
)
from rue.environment.dispatch import install_dispatchers
from rue.environment.runtime import Environment, EnvironmentVars
from rue.environment.sources import (
    DirSource,
    EmptySource,
    EnvSource,
    GitSource,
    Source,
)
from rue.environment.sync import EnvironmentSyncState


install_dispatchers()


__all__ = [
    "Checkpoint",
    "Deletion",
    "Diff",
    "DirSource",
    "EmptySource",
    "EnvSource",
    "Environment",
    "EnvironmentSyncState",
    "EnvironmentVars",
    "FileDelta",
    "FileDiff",
    "FileState",
    "GitSource",
    "PathDelta",
    "PathNotInDiff",
    "PathState",
    "Source",
    "SymlinkDelta",
    "SymlinkState",
    "sources",
]
