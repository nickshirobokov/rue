"""Single test execution."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from functools import partial
from typing import Any
from uuid import uuid4

from rue.assertions.base import AssertionResult
from rue.context import (
    ResolverContext,
    TestContext,
    assertions_collector,
    get_runner,
    resolver_context_scope,
    test_context_scope,
    test_tracer_scope,
)
from rue.resources import ResourceResolver
from rue.resources.resolver import Scope
from rue.testing.execution.interfaces import Test
from rue.testing.execution.result_builder import ResultBuilder
from rue.testing.models import TestDefinition, TestExecution, TestResult, TestStatus
from rue.testing.outcomes import FailTest, SkipTest, XFailTest
from rue.testing.tracing import TestTracer


logger = logging.getLogger(__name__)


@dataclass
class SingleTest(Test):
    """Executes a single test directly."""

    definition: TestDefinition
    params: dict[str, Any]
    result_builder: ResultBuilder

    def __post_init__(self) -> None:
        """Validate that this test has no modifiers."""
        if self.definition.modifiers:
            raise ValueError("SingleTest should not have modifiers")

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        """Execute the test and return result."""
        runner = get_runner()

        if runner is not None and runner.stop_flag:
            return TestExecution(
                definition=self.definition,
                result=TestResult(
                    status=TestStatus.SKIPPED,
                    duration_ms=0,
                    error=Exception("Run stopped early"),
                ),
                execution_id=uuid4(),
            )

        if self.definition.skip_reason:
            return TestExecution(
                definition=self.definition,
                result=TestResult(
                    status=TestStatus.SKIPPED,
                    duration_ms=0,
                    error=Exception(self.definition.skip_reason),
                ),
                execution_id=uuid4(),
            )

        exec_id = uuid4()

        # fork resolver for case isolation
        forked_resolver = resolver.fork_for_case()

        assertion_results: list[AssertionResult] = []
        error: Exception | None = None
        tracer = TestTracer(
            otel_enabled=runner.otel_enabled if runner is not None else False,
            otel_content=runner.otel_content if runner is not None else True,
        )

        with test_tracer_scope(tracer):
            tracer.start_otel_root_span(self.definition)
            if tracer.otel_enabled:
                assert runner is not None
                assert runner.current_run is not None
                tracer.start_otel_trace(
                    run_id=runner.current_run.run_id,
                    execution_id=exec_id,
                )

            ctx = TestContext(
                item=self.definition,
                execution_id=exec_id,
            )
            imperative_outcome: TestStatus | None = None

            with test_context_scope(ctx), assertions_collector(assertion_results):
                try:
                    semaphore = (
                        runner.semaphore
                        if runner and runner.semaphore
                        else contextlib.nullcontext()
                    )

                    async with semaphore:
                        start = time.perf_counter()
                        kwargs = await self._resolve_params(forked_resolver)

                        if runner and runner.stop_flag:
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

            with test_context_scope(ctx):
                try:
                    await forked_resolver.teardown_scope(Scope.CASE)
                except Exception as teardown_err:
                    logger.warning(f"Error during resource teardown: {teardown_err}")
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
                result = self.result_builder.build(
                    self.definition, duration_ms, assertion_results, error
                )

            tracer.record_otel_result(result)
            tracer.finish_otel_trace()

        if tracer.completed_otel_trace_session is not None and runner is not None:
            await runner.notify_trace_collected(tracer, exec_id)

        return TestExecution(
            definition=self.definition,
            result=result,
            execution_id=exec_id,
        )

    async def _resolve_params(self, resolver: ResourceResolver) -> dict[str, Any]:
        """Resolve test parameters from resources."""
        kwargs = dict(self.params)
        with resolver_context_scope(ResolverContext(consumer_name=self.definition.name)):
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

        call = partial(fn, instance, **kwargs) if instance else partial(fn, **kwargs)

        if self.definition.is_async:
            await call()
        elif self.definition.run_inline:
            call()
        else:
            await asyncio.to_thread(call)


SingleRueTest = SingleTest
