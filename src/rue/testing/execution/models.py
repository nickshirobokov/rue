"""Test execution outcome models."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.assertions.models import AssertionResult
from rue.context.collectors import CURRENT_ASSERTION_RESULTS
from rue.context.runtime import (
    CURRENT_TEST,
    SuiteContext,
    bind,
)
from rue.resources import DependencyResolver
from rue.resources.models import StateSnapshot
from rue.telemetry.models import TelemetryArtifact
from rue.testing.models.spec import SetupFileRef, TestSpec
from rue.testing.outcomes import FailTest, SkipTest, XFailTest


class TestStatus(StrEnum):
    """Test execution status."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"
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
        """Build a result from imperative and observed test execution outcomes."""
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
        """Return the status suffix shown next to test execution names."""
        if self.status == TestStatus.SKIPPED:
            reason = self.error.args[0] if self.error else "skipped"
            return f"skipped ({reason})"
        if self.status == TestStatus.NOT_RUN:
            reason = self.error.args[0] if self.error else "not run"
            return f"not run ({reason})"
        if self.status == TestStatus.XFAILED:
            reason = self.error.args[0] if self.error else "expected failure"
            return f"xfailed ({reason})"
        if self.status == TestStatus.XPASSED:
            return "XPASS"
        return ""


@dataclass
class LoadedTestDef:
    """A discovered test function ready for test execution in this process.

    Pairs a serializable :class:`TestSpec` with the live callable resolved
    by the loader.  The ``spec`` is the cross-process-safe record; ``fn`` is
    the process-local binding.

    ``suite_root`` and ``setup_chain`` capture the import context used to
    materialize this callable so expanded leaves still describe the suite they
    came from.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    spec: TestSpec
    fn: Callable[..., Any]
    suite_root: Path = field(default_factory=Path)
    setup_chain: tuple[SetupFileRef, ...] = field(default_factory=tuple)

    async def call_test_fn(
        self,
        kwargs: dict[str, Any],
        *,
        execute_sync_in_thread: bool,
    ) -> None:
        """Call the loaded test function with resolved resource kwargs."""
        instance = None

        if self.spec.locator.class_name:
            cls = self.fn.__globals__.get(self.spec.locator.class_name)
            if cls is None:
                raise RuntimeError(
                    f"Test class '{self.spec.locator.class_name}' not found "
                    f"for test '{self.spec.locator.function_name}'"
                )
            instance = cls()

        call = (
            partial(self.fn, instance, **kwargs)
            if instance
            else partial(self.fn, **kwargs)
        )

        if self.spec.is_async:
            await call()
        elif execute_sync_in_thread:
            await asyncio.to_thread(call)
        else:
            call()

    async def execute_loaded_test(
        self,
        *,
        params: dict[str, Any],
        resolver: DependencyResolver,
        execute_sync_in_thread: bool,
        is_stopped: Callable[[], bool] | None = None,
    ) -> tuple[
        float,
        TestStatus | None,
        BaseException | None,
        list[AssertionResult],
    ]:
        """Resolve resources, execute this test, and return metadata."""
        assertion_results: list[AssertionResult] = []
        error: BaseException | None = None
        imperative_outcome: TestStatus | None = None

        start = time.perf_counter()
        with bind(CURRENT_ASSERTION_RESULTS, assertion_results):
            try:
                kwargs = await resolver.resolve_graph_deps(
                    resolver.registry.get_graph(
                        CURRENT_TEST.get().test_execution_id
                    ),
                    params,
                    consumer_spec=self.spec,
                )
                if is_stopped is not None and is_stopped():
                    imperative_outcome = TestStatus.SKIPPED
                    error = Exception("Suite stopped early")
                else:
                    await self.call_test_fn(
                        kwargs=kwargs,
                        execute_sync_in_thread=execute_sync_in_thread,
                    )
            except SkipTest as raised:
                imperative_outcome = TestStatus.SKIPPED
                error = raised
            except FailTest as raised:
                imperative_outcome = TestStatus.FAILED
                error = raised
            except XFailTest as raised:
                imperative_outcome = TestStatus.XFAILED
                error = raised
            except Exception as raised:
                error = raised

        return (
            (time.perf_counter() - start) * 1000,
            imperative_outcome,
            error,
            assertion_results,
        )


@dataclass
class ExecutedTest:
    """Complete record of a test execution, combining context and result.

    Encapsulates both the test context (inputs/setup) and the result (outcome)
    as a single test execution record.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    definition: LoadedTestDef
    result: TestResult
    test_execution_id: UUID
    telemetry_artifacts: tuple[TelemetryArtifact, ...] = ()
    sub_test_executions: list[ExecutedTest] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Short display label from spec or test_execution_id."""
        dlabel = self.definition.spec.get_label()
        if dlabel:
            return dlabel
        if self.test_execution_id:
            return str(self.test_execution_id)[:8]
        return "case"


@dataclass(frozen=True, slots=True)
class RemoteTestExecutionPayload:
    """Minimal, fully-serializable payload for remote test execution."""

    spec: TestSpec
    suite_root: Path
    setup_chain: tuple[SetupFileRef, ...]
    params: dict[str, Any]
    snapshot: StateSnapshot
    context: SuiteContext
    test_execution_id: UUID


@dataclass(frozen=True, slots=True)
class RemoteTestExecutionResult:
    """Serializable remote test execution outcome."""

    result: TestResult
    telemetry_artifacts: tuple[TelemetryArtifact, ...]
    sync_update: bytes
