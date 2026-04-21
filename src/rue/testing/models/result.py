"""Test result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from rue.assertions.base import AssertionResult


class TestStatus(Enum):
    """Test execution status."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    XFAILED = "xfailed"
    XPASSED = "xpassed"

    @property
    def is_failure(self) -> bool:
        """Check if this status represents a failure."""
        return self in {TestStatus.FAILED, TestStatus.ERROR}


@dataclass
class TestResult:
    """Result of a single test execution."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    status: TestStatus
    duration_ms: float
    error: BaseException | None = None
    assertion_results: list[AssertionResult] = field(default_factory=list)

    @property
    def status_repr(self) -> str:
        if self.status == TestStatus.SKIPPED:
            reason = self.error.args[0] if self.error else "skipped"
            return f"skipped ({reason})"
        if self.status == TestStatus.XFAILED:
            reason = self.error.args[0] if self.error else "expected failure"
            return f"xfailed ({reason})"
        if self.status == TestStatus.XPASSED:
            return "XPASS"
        return ""
