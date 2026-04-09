from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
from collections.abc import Callable, Coroutine

from rue.testing.execution.interfaces import Test
from rue.testing.models.definition import TestDefinition
from rue.testing.models.result import TestExecution, TestResult, TestStatus
from rue.resources.resolver import ResourceResolver
from rue.context.runtime import CURRENT_RUNNER


@dataclass
class CompositeTest(Test):
    """Executes pre-built child tests concurrently and aggregates results."""

    definition: TestDefinition
    min_passes: int
    children: list[Test] = field(default_factory=list)

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        async def run_child(index: int) -> tuple[int, TestExecution]:
            execution = await self.children[index].execute(resolver)
            return index, execution

        sub_executions = await self._run_children(run_child)
        passed = sum(
            1 for e in sub_executions if e.result.status == TestStatus.PASSED
        )
        status = (
            TestStatus.PASSED
            if passed >= self.min_passes
            else TestStatus.FAILED
        )
        duration = sum(e.result.duration_ms for e in sub_executions)
        return TestExecution(
            definition=self.definition,
            result=TestResult(status=status, duration_ms=duration),
            execution_id=uuid4(),
            sub_executions=sub_executions,
        )

    async def _run_children(
        self,
        run_child: Callable[
            [int], Coroutine[Any, Any, tuple[int, TestExecution]]
        ],
    ) -> list[TestExecution]:
        tasks = [
            asyncio.create_task(run_child(index))
            for index in range(len(self.children))
        ]
        sub_executions: list[TestExecution | None] = [None] * len(self.children)
        runner = CURRENT_RUNNER.get()
        try:
            for completed_task in asyncio.as_completed(tasks):
                index, sub_execution = await completed_task
                sub_executions[index] = sub_execution
                if runner:
                    await runner.notify_subtest_complete(
                        self.definition, sub_execution
                    )
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return [e for e in sub_executions if e is not None]
