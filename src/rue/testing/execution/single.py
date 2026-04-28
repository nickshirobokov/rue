"""Single test execution."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from rue.context.process_pool import get_process_pool
from rue.context.runtime import (
    CURRENT_RUN_CONTEXT,
    CURRENT_TEST,
    CURRENT_TEST_TRACER,
    TestContext,
    bind,
)
from rue.resources import ResourceResolver
from rue.resources.models import Scope
from rue.testing.execution.base import ExecutableTest, ExecutionBackend
from rue.testing.execution.worker import (
    ExecutorPayload,
    RemoteExecutionResult,
    run_remote_test,
)
from rue.testing.models import (
    ExecutedTest,
    LoadedTestDef,
    TestResult,
    TestStatus,
)
from rue.testing.tracing import TestTracer


@dataclass
class SingleTest(ExecutableTest):
    """Executes a single test directly or in a subprocess."""

    definition: LoadedTestDef
    params: dict[str, Any]
    node_key: str
    backend: ExecutionBackend = ExecutionBackend.ASYNCIO
    sync_actor_id: int = 1
    children: list[ExecutableTest] = field(
        default_factory=list, init=False, repr=False
    )
    semaphore: asyncio.Semaphore | None = None
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    on_complete: Callable | None = None
    tracer: TestTracer = field(init=False)

    def __post_init__(self) -> None:
        """Initialize derived execution collaborators."""
        if self.definition.spec.modifiers:
            raise ValueError("SingleTest should not have modifiers")
        context = CURRENT_RUN_CONTEXT.get()
        self.tracer = TestTracer.build(
            config=context.config,
            run_id=context.run_id,
        )

    async def _execute(self, resolver: ResourceResolver) -> ExecutedTest:
        exec_id = uuid4()
        match self:
            case SingleTest(is_stopped=is_stopped) if is_stopped():
                return ExecutedTest(
                    definition=self.definition,
                    node_key=self.node_key,
                    result=TestResult(
                        status=TestStatus.SKIPPED,
                        duration_ms=0,
                        error=Exception("Run stopped early"),
                    ),
                    execution_id=exec_id,
                )
            case (
                SingleTest(definition=LoadedTestDef(spec=spec))
            ) if spec.skip_reason:
                return ExecutedTest(
                    definition=self.definition,
                    node_key=self.node_key,
                    result=TestResult(
                        status=TestStatus.SKIPPED,
                        duration_ms=0,
                        error=Exception(spec.skip_reason),
                    ),
                    execution_id=exec_id,
                )

        test_resolver = resolver.fork_for_test()
        ctx = TestContext(
            item=self.definition,
            execution_id=exec_id,
        )
        with ctx:
            match self:
                case SingleTest(backend=ExecutionBackend.SUBPROCESS):
                    return await self._execute_subprocess(test_resolver)
                case SingleTest():
                    return await self._execute_local(test_resolver)

    async def _execute_local(
        self,
        resolver: ResourceResolver,
    ) -> ExecutedTest:
        ctx = CURRENT_TEST.get()
        execution_id = ctx.execution_id
        semaphore = (
            self.semaphore if self.semaphore else contextlib.nullcontext()
        )

        with bind(CURRENT_TEST_TRACER, self.tracer):
            self.tracer.start(self.definition, execution_id=execution_id)
            async with semaphore:
                duration_ms, imperative_outcome, error, assertion_results = (
                    await self.definition.run_loaded_test(
                        params=self.params,
                        resolver=resolver,
                        run_sync_in_thread=self.backend
                        is not ExecutionBackend.MAIN,
                        is_stopped=self.is_stopped,
                    )
                )
            resolver.flush_live_changes(
                [
                    identity
                    for identity in resolver.cached_identities
                    if identity.scope is not Scope.TEST
                ]
            )
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
            node_key=self.node_key,
            result=result,
            execution_id=execution_id,
            telemetry_artifacts=telemetry_artifacts,
        )

    async def _execute_subprocess(
        self,
        resolver: ResourceResolver,
    ) -> ExecutedTest:
        ctx = CURRENT_TEST.get()
        execution_id = ctx.execution_id
        remote_result: RemoteExecutionResult
        context = CURRENT_RUN_CONTEXT.get()

        try:
            semaphore = (
                self.semaphore if self.semaphore else contextlib.nullcontext()
            )
            async with semaphore:
                unresolved_params = tuple(
                    param
                    for param in self.definition.spec.params
                    if param not in self.params
                )
                autouse_names = await resolver.resolve_autouse(
                    self.definition.spec,
                    apply_injection_hook=False,
                )
                await resolver.partially_resolve(
                    unresolved_params,
                    self.params,
                    consumer_spec=self.definition.spec,
                    apply_injection_hook=False,
                )
                snapshot = resolver.export_sync_snapshot(
                    (*autouse_names, *unresolved_params),
                    consumer_spec=self.definition.spec,
                    sync_actor_id=self.sync_actor_id,
                )

                payload = ExecutorPayload(
                    spec=self.definition.spec,
                    suite_root=self.definition.suite_root,
                    setup_chain=self.definition.setup_chain,
                    params=dict(self.params),
                    snapshot=snapshot,
                    context=context,
                    execution_id=execution_id,
                )

                future = get_process_pool().submit(
                    run_remote_test,
                    payload,
                )
                remote_result = await asyncio.wrap_future(future)
                resolver.apply_sync_update(
                    snapshot,
                    remote_result.sync_update,
                )
        finally:
            await resolver.teardown_scope(Scope.TEST)

        return ExecutedTest(
            definition=self.definition,
            node_key=self.node_key,
            result=remote_result.result,
            execution_id=execution_id,
            telemetry_artifacts=remote_result.telemetry_artifacts,
        )
