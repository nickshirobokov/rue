"""Suite-level aggregates and rolled-up suite results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from rue.context.models import SuiteEnvironment
from rue.resources.metrics.models import MetricResult
from rue.testing.execution.models import ExecutedTest, TestStatus


@dataclass
class SuiteResult:
    """Result of a complete suite execution."""

    test_executions: list[ExecutedTest] = field(default_factory=list)
    metric_results: list[MetricResult] = field(default_factory=list)
    total_duration_ms: float = 0
    stopped_early: bool = False

    @property
    def passed(self) -> int:
        """Count of passed tests."""
        return sum(
            1
            for e in self.test_executions
            if e.result.status == TestStatus.PASSED
        )

    @property
    def failed(self) -> int:
        """Count of failed tests."""
        return sum(
            1
            for e in self.test_executions
            if e.result.status == TestStatus.FAILED
        )

    @property
    def errors(self) -> int:
        """Count of errored tests."""
        return sum(
            1
            for e in self.test_executions
            if e.result.status == TestStatus.ERROR
        )

    @property
    def skipped(self) -> int:
        """Count of skipped tests."""
        return sum(
            1
            for e in self.test_executions
            if e.result.status == TestStatus.SKIPPED
        )

    @property
    def xfailed(self) -> int:
        """Count of expected failures."""
        return sum(
            1
            for e in self.test_executions
            if e.result.status == TestStatus.XFAILED
        )

    @property
    def xpassed(self) -> int:
        """Count of unexpected passes for xfail tests."""
        return sum(
            1
            for e in self.test_executions
            if e.result.status == TestStatus.XPASSED
        )

    @property
    def total(self) -> int:
        """Total test count."""
        return len(self.test_executions)


@dataclass
class ExecutedSuite:
    """Complete record of a suite execution.

    This is created for a Rue suite execution and encapsulates
    all information about that execution, including environment metadata and
    test executions with their contexts.

    Access result data via suite.result.* (e.g., suite.result.passed).
    """

    suite_execution_id: UUID = field(default_factory=uuid4)
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None

    environment: SuiteEnvironment = field(
        default_factory=SuiteEnvironment.build_from_current
    )
    result: SuiteResult = field(default_factory=SuiteResult)
