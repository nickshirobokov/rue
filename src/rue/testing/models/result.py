"""Test result models."""

from __future__ import annotations

from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum

from rue.assertions.base import AssertionResult

if TYPE_CHECKING:
    from rue.testing.models.loaded import LoadedTestDef


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

    @classmethod
    def build(
        cls,
        *,
        definition: LoadedTestDef,
        imperative_outcome: TestStatus | None,
        duration_ms: float,
        error: BaseException | None,
        assertion_results: list[AssertionResult],
    ) -> TestResult:
        if imperative_outcome is not None:
            return cls(
                status=imperative_outcome,
                duration_ms=duration_ms,
                error=error,
                assertion_results=assertion_results,
            )

        expect_failure = definition.spec.xfail_reason is not None
        failed_assertions = [
            result for result in assertion_results if not result.passed
        ]
        has_error = error is not None and not isinstance(
            error, AssertionError
        )
        has_assertion_fail = bool(failed_assertions) or isinstance(
            error, AssertionError
        )

        match (has_error, has_assertion_fail, expect_failure):
            case (True, _, True):
                status, result_error = TestStatus.XFAILED, error
            case (True, _, False):
                status, result_error = TestStatus.ERROR, error
            case (_, True, xfail):
                status = TestStatus.XFAILED if xfail else TestStatus.FAILED
                if error is None and failed_assertions:
                    message = (
                        failed_assertions[0].error_message
                        or failed_assertions[0].expression_repr.expr
                    )
                    result_error = AssertionError(message)
                else:
                    result_error = error
            case (_, _, True) if definition.spec.xfail_strict:
                status = TestStatus.FAILED
                result_error = AssertionError(
                    definition.spec.xfail_reason or "xfail test passed"
                )
            case (_, _, True):
                status, result_error = TestStatus.XPASSED, None
            case _:
                status, result_error = TestStatus.PASSED, None

        return cls(
            status=status,
            duration_ms=duration_ms,
            error=result_error,
            assertion_results=assertion_results.copy(),
        )

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
