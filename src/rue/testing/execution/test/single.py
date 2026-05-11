"""Single test execution."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from rue.context.process_pool import LazyProcessPool
from rue.context.runtime import (
    CURRENT_SUITE_CONTEXT,
    CURRENT_TEST,
    CURRENT_TEST_TRACER,
    TestContext,
    bind,
)
from rue.context.scopes import Scope
from rue.resources import DependencyResolver
from rue.testing.execution.backend import ExecutionBackend
from rue.testing.execution.test.base import ExecutableTest
from rue.testing.execution.test.models import (
    ExecutedTest,
    LoadedTestDef,
    RemoteTestExecutionPayload,
    RemoteTestExecutionResult,
    TestResult,
    TestStatus,
)
from rue.testing.execution.worker import (
    execute_remote_test,
)
from rue.testing.tracing import TestTracer


def _never_stopped() -> bool:
    return False


@dataclass
class SingleTest(ExecutableTest):
    """Executes a single test directly or in a subprocess."""

    definition: LoadedTestDef
    params: dict[str, Any]
    test_execution_id: UUID
    backend: ExecutionBackend = ExecutionBackend.ASYNCIO
    sync_actor_id: int = 1
    children: list[ExecutableTest] = field(
        default_factory=list, init=False, repr=False
    )
    semaphore: asyncio.Semaphore | None = None
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    tracer: TestTracer = field(init=False)

    def __post_init__(self) -> None:
        """Initialize derived execution collaborators."""
        if self.definition.spec.modifiers:
            raise ValueError("SingleTest should not have modifiers")
        context = CURRENT_SUITE_CONTEXT.get()
        self.tracer = TestTracer.build(
            config=context.config,
            suite_execution_id=context.suite_execution_id,
        )

    def __getstate__(self) -> dict[str, Any]:
        """Serialize the event-visible test without runtime schedulers."""
        state = self.__dict__.copy()
        state["semaphore"] = None
        state["is_stopped"] = _never_stopped
        state["tracer"] = TestTracer(
            suite_execution_id=self.tracer.suite_execution_id
        )
        return state

    async def _execute(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        with TestContext(test_execution_id=self.test_execution_id):
            match self:
                case SingleTest(is_stopped=is_stopped) if is_stopped():
                    return ExecutedTest(
                        definition=self.definition,
                        result=TestResult(
                            status=TestStatus.SKIPPED,
                            duration_ms=0,
                            error=Exception("Suite stopped early"),
                        ),
                        test_execution_id=self.test_execution_id,
                    )
                case SingleTest(definition=LoadedTestDef(spec=spec)) if (
                    spec.skip_reason
                ):
                    return ExecutedTest(
                        definition=self.definition,
                        result=TestResult(
                            status=TestStatus.SKIPPED,
                            duration_ms=0,
                            error=Exception(spec.skip_reason),
                        ),
                        test_execution_id=self.test_execution_id,
                    )
                case SingleTest(backend=ExecutionBackend.SUBPROCESS):
                    return await self._execute_subprocess(resolver)
                case SingleTest():
                    return await self._execute_local(resolver)

    async def _execute_local(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        test_execution_id = CURRENT_TEST.get().test_execution_id
        semaphore = (
            self.semaphore if self.semaphore else contextlib.nullcontext()
        )

        with bind(CURRENT_TEST_TRACER, self.tracer):
            self.tracer.start(
                self.definition,
                test_execution_id=test_execution_id,
            )
            async with semaphore:
                (
                    duration_ms,
                    imperative_outcome,
                    error,
                    assertion_results,
                ) = await self.definition.execute_loaded_test(
                    params=self.params,
                    resolver=resolver,
                    execute_sync_in_thread=self.backend
                    is not ExecutionBackend.MAIN,
                    is_stopped=self.is_stopped,
                )
            resolver.transfer.flush_visible_shared_resources()
            try:
                await resolver.teardown(Scope.TEST)
            except Exception as teardown_error:
                logging.warning(
                    f"Error during resource teardown: {teardown_error}"
                )
                if error is None:
                    error = teardown_error
            result = TestResult.build(
                definition=self.definition,
                imperative_outcome=imperative_outcome,
                duration_ms=duration_ms,
                error=error,
                assertion_results=assertion_results,
            )
            self.tracer.record_result(result)
            telemetry_artifacts = self.tracer.finish()

        return ExecutedTest(
            definition=self.definition,
            result=result,
            test_execution_id=test_execution_id,
            telemetry_artifacts=telemetry_artifacts,
        )

    async def _execute_subprocess(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        suite_context = CURRENT_SUITE_CONTEXT.get()
        test_execution_id = CURRENT_TEST.get().test_execution_id
        remote_result: RemoteTestExecutionResult

        try:
            semaphore = (
                self.semaphore if self.semaphore else contextlib.nullcontext()
            )
            async with semaphore:
                await resolver.resolve_graph_deps(
                    resolver.registry.get_graph(test_execution_id),
                    {},
                    consumer_spec=self.definition.spec,
                    preload=True,
                )
                snapshot = resolver.transfer.export_snapshot(
                    test_execution_id,
                    actor_id=self.sync_actor_id,
                )

                payload = RemoteTestExecutionPayload(
                    spec=self.definition.spec,
                    suite_root=self.definition.suite_root,
                    setup_chain=self.definition.setup_chain,
                    params=dict(self.params),
                    snapshot=snapshot,
                    context=suite_context,
                    test_execution_id=test_execution_id,
                )

                future = LazyProcessPool.current_executor().submit(
                    execute_remote_test,
                    payload,
                )
                remote_result = await asyncio.wrap_future(future)
                resolver.transfer.apply_update(
                    snapshot,
                    remote_result.sync_update,
                )
        finally:
            await resolver.teardown(Scope.TEST)

        return ExecutedTest(
            definition=self.definition,
            result=remote_result.result,
            test_execution_id=test_execution_id,
            telemetry_artifacts=remote_result.telemetry_artifacts,
        )
