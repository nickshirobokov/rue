"""Remote single-test execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_RESOURCE_CONSUMER_KIND,
    bind,
)
from rue.resources import ResourceResolver
from rue.resources.models import ResourceBlueprint, Scope
from rue.testing.execution.interfaces import ExecutableTest
from rue.context.process_pool import get_process_pool
from rue.testing.execution.remote.worker import run_remote_test
from rue.testing.models import ExecutedTest, LoadedTestDef, TestResult, TestStatus
from rue.testing.models.spec import SetupFileRef, TestSpec


@dataclass(frozen=True, slots=True)
class ExecutorPayload:
    """Minimal, fully-serializable payload for remote test execution."""

    spec: TestSpec
    suite_root: Path
    setup_chain: tuple[SetupFileRef, ...]
    params: dict[str, Any]
    blueprint: ResourceBlueprint
    run_id: UUID | None = None


@dataclass
class RemoteSingleTest(ExecutableTest):
    """Executes a single test in a separate worker process.

    Resolves every resource needed by the test in the parent process, builds a
    serializable :class:`ResourceBlueprint`, hands the packaged payload to a
    :class:`ProcessPoolExecutor`, and wraps the returned :class:`TestResult`
    into an :class:`ExecutedTest` using the locally-held ``definition``.
    """

    definition: LoadedTestDef
    params: dict[str, Any]
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    on_complete: Callable | None = None

    def __post_init__(self) -> None:
        if self.definition.spec.modifiers:
            raise ValueError("RemoteSingleTest should not have modifiers")

    async def execute(self, resolver: ResourceResolver) -> ExecutedTest:
        if self.is_stopped():
            return await self._finalize(
                TestResult(
                    status=TestStatus.SKIPPED,
                    duration_ms=0,
                    error=Exception("Run stopped early"),
                )
            )

        if self.definition.spec.skip_reason:
            return await self._finalize(
                TestResult(
                    status=TestStatus.SKIPPED,
                    duration_ms=0,
                    error=Exception(self.definition.spec.skip_reason),
                )
            )

        forked = resolver.fork_for_test()

        try:
            kwargs = await self._resolve_params(forked)
            resource_names = [
                name for name in self.definition.spec.params if name in kwargs
                and name not in self.params
            ]
            blueprint = forked.build_blueprint(
                resource_names,
                request_path=self.definition.spec.module_path,
            )

            payload = ExecutorPayload(
                spec=self.definition.spec,
                suite_root=self.definition.suite_root,
                setup_chain=self.definition.setup_chain,
                params=dict(self.params),
                blueprint=blueprint,
            )

            future = get_process_pool().submit(run_remote_test, payload)
            result = await asyncio.wrap_future(future)
        finally:
            await forked.teardown_scope(Scope.TEST)

        return await self._finalize(result)

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

    async def _finalize(self, result: TestResult) -> ExecutedTest:
        execution = ExecutedTest(
            definition=self.definition,
            result=result,
            execution_id=uuid4(),
        )
        if self.on_complete:
            await self.on_complete(execution)
        return execution
