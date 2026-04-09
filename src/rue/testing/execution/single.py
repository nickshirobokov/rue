"""Single test execution."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any
from uuid import uuid4

from rue.assertions.base import AssertionResult
from rue.context.collectors import CURRENT_ASSERTION_RESULTS
from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_TEST,
    CURRENT_TEST_TRACER,
    TestContext,
    bind,
)
from rue.resources import ResourceResolver
from rue.resources.resolver import Scope
from rue.testing.execution.interfaces import Test
from rue.testing.models import (
    TestDefinition,
    TestExecution,
    TestResult,
    TestStatus,
)
from rue.testing.outcomes import FailTest, SkipTest, XFailTest
from rue.testing.tracing import TestTracer


logger = logging.getLogger(__name__)


@dataclass
class SingleTest(Test):
    """Executes a single test directly."""

    definition: TestDefinition
    params: dict[str, Any]
    tracer: TestTracer
    semaphore: asyncio.Semaphore | None = None
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    on_complete: Callable | None = None
    on_trace_collected: Callable | None = None

    def __post_init__(self) -> None:
        """Validate that this test has no modifiers."""
        if self.definition.modifiers:
            raise ValueError("SingleTest should not have modifiers")

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        """Execute the test and return result."""
        if self.is_stopped():
            execution = TestExecution(
                definition=self.definition,
                result=TestResult(
                    status=TestStatus.SKIPPED,
                    duration_ms=0,
                    error=Exception("Run stopped early"),
                ),
                execution_id=uuid4(),
            )
            if self.on_complete:
                await self.on_complete(execution)
            return execution

        if self.definition.skip_reason:
            execution = TestExecution(
                definition=self.definition,
                result=TestResult(
                    status=TestStatus.SKIPPED,
                    duration_ms=0,
                    error=Exception(self.definition.skip_reason),
                ),
                execution_id=uuid4(),
            )
            if self.on_complete:
                await self.on_complete(execution)
            return execution

        exec_id = uuid4()

        forked_resolver = resolver.fork_for_case()

        assertion_results: list[AssertionResult] = []
        error: BaseException | None = None

        with bind(CURRENT_TEST_TRACER, self.tracer):
            self.tracer.start_otel_root_span(self.definition)
            self.tracer.start_otel_trace(execution_id=exec_id)

            ctx = TestContext(
                item=self.definition,
                execution_id=exec_id,
            )
            imperative_outcome: TestStatus | None = None

            with (
                bind(CURRENT_TEST, ctx),
                bind(CURRENT_ASSERTION_RESULTS, assertion_results),
            ):
                try:
                    semaphore = (
                        self.semaphore
                        if self.semaphore
                        else contextlib.nullcontext()
                    )

                    async with semaphore:
                        start = time.perf_counter()
                        kwargs = await self._resolve_params(forked_resolver)

                        if self.is_stopped():
                            imperative_outcome = TestStatus.SKIPPED
                            error = Exception("Run stopped early")
                        else:
                            await self._invoke(kwargs)

                except SkipTest as e:
                    imperative_outcome = TestStatus.SKIPPED
                    error = e
                except FailTest as e:
                    imperative_outcome = TestStatus.FAILED
                    error = e
                except XFailTest as e:
                    imperative_outcome = TestStatus.XFAILED
                    error = e
                except Exception as e:  # noqa: BLE001
                    error = e

            duration_ms = (time.perf_counter() - start) * 1000

            with bind(CURRENT_TEST, ctx):
                try:
                    await forked_resolver.teardown_scope(Scope.CASE)
                except Exception as teardown_err:
                    logger.warning(
                        f"Error during resource teardown: {teardown_err}"
                    )
                    if error is None:
                        error = teardown_err

            if imperative_outcome is not None:
                result = TestResult(
                    status=imperative_outcome,
                    duration_ms=duration_ms,
                    error=error,
                    assertion_results=assertion_results,
                )
            else:
                expect_failure = self.definition.xfail_reason is not None
                failed_assertions = [
                    ar for ar in assertion_results if not ar.passed
                ]
                has_error = error is not None and not isinstance(
                    error, AssertionError
                )
                has_assertion_fail = bool(failed_assertions) or isinstance(
                    error, AssertionError
                )

                match (has_error, has_assertion_fail, expect_failure):
                    # Unexpected exception in a test marked xfail
                    case (True, _, True):
                        status, result_error = TestStatus.XFAILED, error
                    # Unexpected exception in a normal test
                    case (True, _, False):
                        status, result_error = TestStatus.ERROR, error
                    # Assertion-level failure (explicit or via AssertionError)
                    case (_, True, xfail):
                        status = (
                            TestStatus.XFAILED if xfail else TestStatus.FAILED
                        )
                        if error is None and failed_assertions:
                            msg = (
                                failed_assertions[0].error_message
                                or failed_assertions[0].expression_repr.expr
                            )
                            result_error = AssertionError(msg)
                        else:
                            result_error = error
                    # xfail test passed when it shouldn't have (strict mode)
                    case (_, _, True) if self.definition.xfail_strict:
                        status = TestStatus.FAILED
                        result_error = AssertionError(
                            self.definition.xfail_reason or "xfail test passed"
                        )
                    # xfail test passed unexpectedly (non-strict)
                    case (_, _, True):
                        status, result_error = TestStatus.XPASSED, None
                    # Clean pass
                    case _:
                        status, result_error = TestStatus.PASSED, None

                result = TestResult(
                    status=status,
                    duration_ms=duration_ms,
                    error=result_error,
                    assertion_results=assertion_results.copy(),
                )

            self.tracer.record_otel_result(result)
            self.tracer.finish_otel_trace()

        if self.tracer.completed_otel_trace_session is not None and self.on_trace_collected:
            await self.on_trace_collected(self.tracer, exec_id)

        execution = TestExecution(
            definition=self.definition,
            result=result,
            execution_id=exec_id,
        )
        if self.on_complete:
            await self.on_complete(execution)
        return execution

    async def _resolve_params(
        self, resolver: ResourceResolver
    ) -> dict[str, Any]:
        """Resolve test parameters from resources."""
        kwargs = dict(self.params)
        with bind(CURRENT_RESOURCE_CONSUMER, self.definition.name):
            for param in self.definition.params:
                if param not in kwargs:
                    kwargs[param] = await resolver.resolve(param)
        return kwargs

    async def _invoke(self, kwargs: dict[str, Any]) -> None:
        """Invoke the test function."""
        fn = self.definition.fn
        instance = None

        if self.definition.class_name:
            cls = fn.__globals__.get(self.definition.class_name)

            if cls is None:
                raise RuntimeError(
                    f"Test class '{self.definition.class_name}' not found for test '{self.definition.name}'"
                )

            instance = cls()

        call = (
            partial(fn, instance, **kwargs)
            if instance
            else partial(fn, **kwargs)
        )

        if self.definition.is_async:
            await call()
        elif self.definition.inline:
            call()
        else:
            await asyncio.to_thread(call)
