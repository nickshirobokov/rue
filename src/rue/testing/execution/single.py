"""Single test execution."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from rue.assertions.base import AssertionResult
from rue.config import Config
from rue.context.collectors import CURRENT_ASSERTION_RESULTS
from rue.context.process_pool import get_process_pool
from rue.context.runtime import (
    CURRENT_TEST,
    CURRENT_TEST_TRACER,
    TestContext,
    bind,
)
from rue.resources import ResourceResolver
from rue.resources.models import Scope
from rue.testing.execution.interfaces import ExecutableTest
from rue.testing.execution.remote.models import ExecutorPayload
from rue.testing.execution.types import ExecutionBackend
from rue.testing.models import (
    ExecutedTest,
    LoadedTestDef,
    TestResult,
    TestStatus,
)
from rue.testing.outcomes import FailTest, SkipTest, XFailTest
from rue.testing.tracing import TestTracer, build_test_tracer


@dataclass
class SingleTest(ExecutableTest):
    """Executes a single test directly or in a subprocess."""

    definition: LoadedTestDef
    params: dict[str, Any]
    backend: ExecutionBackend = ExecutionBackend.ASYNCIO
    config: Config = field(default_factory=Config)
    run_id: UUID = field(default_factory=uuid4)
    sync_actor_id: int = 1
    semaphore: asyncio.Semaphore | None = None
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    on_complete: Callable | None = None
    tracer: TestTracer = field(init=False)

    def __post_init__(self) -> None:
        if self.definition.spec.modifiers:
            raise ValueError("SingleTest should not have modifiers")
        self.tracer = build_test_tracer(
            config=self.config,
            run_id=self.run_id,
        )

    async def _execute(self, resolver: ResourceResolver) -> ExecutedTest:
        exec_id = uuid4()
        match self:
            case SingleTest(is_stopped=is_stopped) if is_stopped():
                return ExecutedTest(
                    definition=self.definition,
                    result=TestResult(
                        status=TestStatus.SKIPPED,
                        duration_ms=0,
                        error=Exception("Run stopped early"),
                    ),
                    execution_id=exec_id,
                )
            case SingleTest(definition=LoadedTestDef(spec=spec)) if spec.skip_reason:
                return ExecutedTest(
                    definition=self.definition,
                    result=TestResult(
                        status=TestStatus.SKIPPED,
                        duration_ms=0,
                        error=Exception(spec.skip_reason),
                    ),
                    execution_id=exec_id,
                )
            case SingleTest(backend=ExecutionBackend.SUBPROCESS):
                return await self._execute_subprocess(
                    resolver.fork_for_test(),
                    execution_id=exec_id,
                )
            case SingleTest():
                return await self._execute_local(
                    resolver.fork_for_test(),
                    execution_id=exec_id,
                )

    async def _execute_local(
        self,
        resolver: ResourceResolver,
        *,
        execution_id: UUID,
    ) -> ExecutedTest:
        semaphore = self.semaphore if self.semaphore else contextlib.nullcontext()
        assertion_results: list[AssertionResult] = []
        error: BaseException | None = None
        imperative_outcome: TestStatus | None = None
        telemetry_artifacts = ()
        ctx = TestContext(item=self.definition, execution_id=execution_id)

        with bind(CURRENT_TEST_TRACER, self.tracer):
            self.tracer.start(self.definition, execution_id=execution_id)
            with (
                bind(CURRENT_TEST, ctx),
                bind(CURRENT_ASSERTION_RESULTS, assertion_results),
            ):
                try:
                    async with semaphore:
                        start = time.perf_counter()
                        unresolved_params = tuple(
                            param
                            for param in self.definition.spec.params
                            if param not in self.params
                        )
                        kwargs = await resolver.partially_resolve(
                            unresolved_params,
                            self.params,
                        )
                        if self.is_stopped():
                            imperative_outcome = TestStatus.SKIPPED
                            error = Exception("Run stopped early")
                        else:
                            await self.definition.call_test_fn(
                                kwargs=kwargs,
                                run_sync_in_thread=self.backend
                                is not ExecutionBackend.MAIN,
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
                except Exception as raised:  # noqa: BLE001
                    error = raised

            duration_ms = (time.perf_counter() - start) * 1000
            resolver.flush_live_changes(
                [
                    identity
                    for identity in resolver.cached_identities
                    if identity.scope is not Scope.TEST
                ]
            )
            with bind(CURRENT_TEST, ctx):
                try:
                    await resolver.teardown_scope(Scope.TEST)
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
            execution_id=execution_id,
            telemetry_artifacts=telemetry_artifacts,
        )

    async def _execute_subprocess(
        self,
        resolver: ResourceResolver,
        *,
        execution_id: UUID,
    ) -> ExecutedTest:
        ctx = TestContext(item=self.definition, execution_id=execution_id)

        try:
            semaphore = self.semaphore if self.semaphore else contextlib.nullcontext()
            with bind(CURRENT_TEST, ctx):
                async with semaphore:
                    unresolved_params = tuple(
                        param
                        for param in self.definition.spec.params
                        if param not in self.params
                    )
                    kwargs = await resolver.partially_resolve(
                        unresolved_params,
                        self.params,
                        apply_injection_hook=False,
                    )
                    snapshot = resolver.export_sync_snapshot(
                        unresolved_params,
                        request_path=self.definition.spec.module_path,
                        sync_actor_id=self.sync_actor_id,
                    )

                    payload = ExecutorPayload(
                        spec=self.definition.spec,
                        suite_root=self.definition.suite_root,
                        setup_chain=self.definition.setup_chain,
                        params=dict(self.params),
                        snapshot=snapshot,
                        config=self.config,
                        run_id=self.run_id,
                        execution_id=execution_id,
                    )

                    future = get_process_pool().submit(run_remote_test, payload)
                    remote_result = await asyncio.wrap_future(future)
                    resolver.apply_sync_update(
                        snapshot,
                        remote_result.sync_update,
                    )
        finally:
            with bind(CURRENT_TEST, ctx):
                await resolver.teardown_scope(Scope.TEST)

        return ExecutedTest(
            definition=self.definition,
            result=remote_result.result,
            execution_id=execution_id,
            telemetry_artifacts=remote_result.telemetry_artifacts,
        )


from rue.testing.execution.remote.worker import run_remote_test
