"""Run-level models."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import distributions
from uuid import UUID, uuid4

from pydantic import BaseModel

from rue.resources.metrics.base import MetricResult
from rue.testing.models.executed import ExecutedTest
from rue.testing.models.result import TestStatus


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


@dataclass
class RunResult:
    """Result of a complete test run."""

    executions: list[ExecutedTest] = field(default_factory=list)
    metric_results: list[MetricResult] = field(default_factory=list)
    total_duration_ms: float = 0
    stopped_early: bool = False

    @property
    def passed(self) -> int:
        """Count of passed tests."""
        return sum(1 for e in self.executions if e.status == TestStatus.PASSED)

    @property
    def failed(self) -> int:
        """Count of failed tests."""
        return sum(1 for e in self.executions if e.status == TestStatus.FAILED)

    @property
    def errors(self) -> int:
        """Count of errored tests."""
        return sum(1 for e in self.executions if e.status == TestStatus.ERROR)

    @property
    def skipped(self) -> int:
        """Count of skipped tests."""
        return sum(1 for e in self.executions if e.status == TestStatus.SKIPPED)

    @property
    def xfailed(self) -> int:
        """Count of expected failures."""
        return sum(1 for e in self.executions if e.status == TestStatus.XFAILED)

    @property
    def xpassed(self) -> int:
        """Count of unexpected passes for xfail tests."""
        return sum(1 for e in self.executions if e.status == TestStatus.XPASSED)

    @property
    def total(self) -> int:
        """Total test count."""
        return len(self.executions)


@dataclass
class Run:
    """Complete record of a test run, combining environment and results.

    This is created at the top level of a rue test run and encapsulates
    all information about the run, including environment metadata and
    test executions with their contexts.

    Access result data via run.result.* (e.g., run.result.passed).
    """

    run_id: UUID = field(default_factory=uuid4)
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None

    environment: RunEnvironment = field(
        default_factory=RunEnvironment.build_from_current
    )
    result: RunResult = field(default_factory=RunResult)
