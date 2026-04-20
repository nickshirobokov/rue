"""Remote single-test execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from deepdiff import DeepDiff, Delta

from rue.config import Config
from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_RESOURCE_CONSUMER_KIND,
    CURRENT_TEST,
    TestContext,
    bind,
)
from rue.context.process_pool import get_process_pool
from rue.resources import ResourceResolver
from rue.resources.models import Scope
from rue.testing.execution.interfaces import ExecutableTest
from rue.testing.execution.remote.models import ExecutorPayload
from rue.testing.execution.remote.worker import run_remote_test
from rue.testing.models import (
    ExecutedTest,
    LoadedTestDef,
    TestResult,
    TestStatus,
)


@dataclass
class RemoteSingleTest(ExecutableTest):
    """Executes a single test in a separate worker process.

    Resolves every resource needed by the test in the parent process, builds a
    serializable :class:`ResolverSnapshot`, hands the packaged payload to a
    :class:`ProcessPoolExecutor`, and wraps the returned :class:`TestResult`
    into an :class:`ExecutedTest` using the locally-held ``definition``.
    """

    definition: LoadedTestDef
    params: dict[str, Any]
    config: Config = field(default_factory=Config)
    run_id: UUID = field(default_factory=uuid4)
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    on_complete: Callable | None = None

    def __post_init__(self) -> None:
        if self.definition.spec.modifiers:
            raise ValueError("RemoteSingleTest should not have modifiers")

    async def execute(self, resolver: ResourceResolver) -> ExecutedTest:
        exec_id = uuid4()
        if self.is_stopped():
            return await self._finalize(
                TestResult(
                    status=TestStatus.SKIPPED,
                    duration_ms=0,
                    error=Exception("Run stopped early"),
                ),
                execution_id=exec_id,
            )

        if self.definition.spec.skip_reason:
            return await self._finalize(
                TestResult(
                    status=TestStatus.SKIPPED,
                    duration_ms=0,
                    error=Exception(self.definition.spec.skip_reason),
                ),
                execution_id=exec_id,
            )

        forked = resolver.fork_for_test()

        try:
            kwargs = await self._resolve_params(forked)
            resource_names = [
                name
                for name in self.definition.spec.params
                if name in kwargs and name not in self.params
            ]
            snapshot = forked.build_snapshot(
                resource_names,
                request_path=self.definition.spec.module_path,
                topological=True,
            )

            payload = ExecutorPayload(
                spec=self.definition.spec,
                suite_root=self.definition.suite_root,
                setup_chain=self.definition.setup_chain,
                params=dict(self.params),
                snapshot=snapshot,
                config=self.config,
                run_id=self.run_id,
                execution_id=exec_id,
            )

            future = get_process_pool().submit(run_remote_test, payload)
            remote_result = await asyncio.wrap_future(future)
            parent_snapshot = forked.build_snapshot(
                list(payload.snapshot.res_specs),
                request_path=self.definition.spec.module_path,
                only_cached_roots=True,
            )
            base_payload = forked.snapshot_payload(payload.snapshot)
            parent_diff = DeepDiff(
                base_payload,
                forked.snapshot_payload(parent_snapshot),
                verbose_level=2,
            )
            merged_payload = base_payload + Delta(parent_diff)
            merged_payload = merged_payload + Delta(remote_result.worker_diff)
            forked.apply_snapshot_to_state(merged_payload)
            result = remote_result.result
        finally:
            ctx = TestContext(item=self.definition, execution_id=exec_id)
            with bind(CURRENT_TEST, ctx):
                await forked.teardown_scope(Scope.TEST)

        return await self._finalize(
            result,
            execution_id=exec_id,
            telemetry_artifacts=remote_result.telemetry_artifacts,
        )

    async def _resolve_params(
        self, resolver: ResourceResolver
    ) -> dict[str, Any]:
        """Resolve test parameters from resources."""
        kwargs = dict(self.params)
        with (
            bind(CURRENT_RESOURCE_CONSUMER, self.definition.spec.name),
            bind(CURRENT_RESOURCE_CONSUMER_KIND, "test"),
        ):
            for param in self.definition.spec.params:
                if param not in kwargs:
                    kwargs[param] = await resolver.resolve(param)
        return kwargs

    async def _finalize(
        self,
        result: TestResult,
        *,
        execution_id: UUID,
        telemetry_artifacts: tuple = (),
    ) -> ExecutedTest:
        execution = ExecutedTest(
            definition=self.definition,
            result=result,
            execution_id=execution_id,
            telemetry_artifacts=telemetry_artifacts,
        )
        if self.on_complete:
            await self.on_complete(execution)
        return execution
