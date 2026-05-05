"""Run-level result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from rue.context.models import RunEnvironment
from rue.resources.metrics.models import MetricResult
from rue.testing.models.executed import ExecutedTest
from rue.testing.models.result import TestStatus


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
class ExecutedRun:
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
