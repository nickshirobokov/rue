"""Composite test execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from rue.resources.resolver import DependencyResolver
from rue.testing.execution.base import ExecutableTest, ExecutionBackend
from rue.testing.models.executed import ExecutedTest
from rue.testing.models.loaded import LoadedTestDef
from rue.testing.models.result import TestResult, TestStatus


@dataclass
class CompositeTest(ExecutableTest):
    """Executes pre-built child tests concurrently and aggregates results."""

    definition: LoadedTestDef
    backend: ExecutionBackend
    min_passes: int
    execution_id: UUID
    children: list[ExecutableTest] = field(default_factory=list)
    on_complete: Callable | None = None

    async def _execute(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        if self.backend is ExecutionBackend.MAIN:
            sub_executions = []
            for child in self.children:
                sub_executions.append(await child.execute(resolver))
        else:

            async def run_child(index: int) -> tuple[int, ExecutedTest]:
                execution = await self.children[index].execute(resolver)
                return index, execution

            sub_executions = await self._run_children(run_child)
        passed = sum(
            1
            for execution in sub_executions
            if execution.status is TestStatus.PASSED
        )
        status = (
            TestStatus.PASSED
            if passed >= self.min_passes
            else TestStatus.FAILED
        )
        duration = sum(
            execution.result.duration_ms for execution in sub_executions
        )
        return ExecutedTest(
            definition=self.definition,
            result=TestResult(status=status, duration_ms=duration),
            execution_id=self.execution_id,
            sub_executions=sub_executions,
        )

    async def _run_children(
        self,
        run_child: Callable[
            [int], Coroutine[Any, Any, tuple[int, ExecutedTest]]
        ],
    ) -> list[ExecutedTest]:
        tasks = [
            asyncio.create_task(run_child(index))
            for index in range(len(self.children))
        ]
        sub_executions: list[ExecutedTest | None] = [None] * len(self.children)
        try:
            for completed_task in asyncio.as_completed(tasks):
                index, sub_execution = await completed_task
                sub_executions[index] = sub_execution
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return [
            execution
            for execution in sub_executions
            if execution is not None
        ]
