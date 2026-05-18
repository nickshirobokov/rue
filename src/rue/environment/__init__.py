"""Rue Environment resource: filesystem + env-var sandbox for tests."""

from __future__ import annotations

from rue.environment import sources
from rue.environment.checkpoint import (
    Checkpoint,
    CheckpointDelta,
    Deletion,
    FileDelta,
    FileState,
    PathDelta,
    PathNotInDiff,
    PathState,
    SymlinkDelta,
    SymlinkState,
)
from rue.environment.diff import FileDiff
from rue.environment.dispatch import install_dispatchers
from rue.environment.env import Environment
from rue.environment.sources import (
    DirSource,
    EmptySource,
    EnvSource,
    GitSource,
    Source,
)
from rue.environment.sync import EnvironmentSyncState
from rue.environment.var import EnvVars


install_dispatchers()


__all__ = [
    "Checkpoint",
    "CheckpointDelta",
    "Deletion",
    "DirSource",
    "EmptySource",
    "EnvSource",
    "EnvVars",
    "Environment",
    "EnvironmentSyncState",
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
