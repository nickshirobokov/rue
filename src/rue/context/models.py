"""Shared context models."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import distributions
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel


if TYPE_CHECKING:
    from rue.context.scopes import Scope


@dataclass(frozen=True, slots=True)
class ScopeOwner:
    """Runtime owner for resolved injected dependencies."""

    scope: Scope
    test_execution_id: UUID | None = None
    suite_execution_id: UUID | None = None
    module_path: Path | None = None

    @property
    def key(self) -> str:
        """Stable short id for this owner (paths, cache keys, workers).

        Deterministic across parent and worker processes so reflink-clone
        targets land at the same path on both sides.
        """
        parts: list[str] = [self.scope.value]
        match self.scope:
            case Scope.SUITE:
                parts.append(str(self.suite_execution_id))
            case Scope.MODULE:
                parts.append(str(self.suite_execution_id))
                parts.append(str(self.module_path))
            case Scope.TEST:
                parts.append(str(self.test_execution_id))
        raw = "|".join(parts).encode("utf-8")
        return hashlib.blake2b(raw, digest_size=12).hexdigest()


class SuiteHost(BaseModel):
    """Metadata about the host machine where tests were executed."""

    commit_hash: str | None = None
    branch: str | None = None
    dirty: bool | None = None

    python_version: str
    platform: str
    hostname: str
    working_directory: str
    rue_version: str

    @classmethod
    def build_from_current(cls) -> SuiteHost:
        """Build host metadata from the current process."""
        commit_hash = None
        branch = None
        dirty = None
        if shutil.which("git") is not None:
            in_repo = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                check=False,
                text=True,
            )
            if in_repo.returncode == 0:
                commit = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                current_branch = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                if commit.returncode == 0:
                    commit_hash = commit.stdout.strip() or None
                if current_branch.returncode == 0:
                    branch = current_branch.stdout.strip() or None
                if status.returncode == 0:
                    dirty = bool(status.stdout.strip())

        return cls(
            commit_hash=commit_hash,
            branch=branch,
            dirty=dirty,
            python_version=sys.version.split()[0],
            platform=platform.platform(),
            hostname=socket.gethostname(),
            working_directory=os.getcwd(),
            rue_version=next(
                (dist.version for dist in distributions(name="rue")),
                "0.0.0",
            ),
        )


from rue.context.scopes import Scope  # noqa: E402
