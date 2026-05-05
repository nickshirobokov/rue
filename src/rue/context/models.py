"""Shared context models."""

from __future__ import annotations

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
    execution_id: UUID | None = None
    run_id: UUID | None = None
    module_path: Path | None = None


class RunEnvironment(BaseModel):
    """Metadata about the environment where tests were executed."""

    commit_hash: str | None = None
    branch: str | None = None
    dirty: bool | None = None

    python_version: str
    platform: str
    hostname: str
    working_directory: str
    rue_version: str

    @classmethod
    def build_from_current(cls) -> RunEnvironment:
        """Build environment metadata from the current process."""
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
