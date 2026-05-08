"""Composite test execution."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from rue.resources.resolver import DependencyResolver
from rue.testing.execution.backend import ExecutionBackend
from rue.testing.execution.models import (
    ExecutedTest,
    LoadedTestDef,
    TestResult,
    TestStatus,
)
from rue.testing.execution.test.base import ExecutableTest


@dataclass
class CompositeTest(ExecutableTest):
    """Executes pre-built child tests concurrently and aggregates results."""

    definition: LoadedTestDef
    backend: ExecutionBackend
    min_passes: int
    test_execution_id: UUID
    children: list[ExecutableTest] = field(default_factory=list)

    async def _execute(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        if self.backend is ExecutionBackend.MAIN:
            sub_test_executions = []
            for child in self.children:
                sub_test_executions.append(await child.execute(resolver))
        else:

            async def execute_child(index: int) -> tuple[int, ExecutedTest]:
                execution = await self.children[index].execute(resolver)
                return index, execution

            sub_test_executions = await self._execute_children(execute_child)
        passed = sum(
            1
            for execution in sub_test_executions
            if execution.result.status is TestStatus.PASSED
        )
        status = (
            TestStatus.PASSED
            if passed >= self.min_passes
            else TestStatus.FAILED
        )
        duration = sum(
            execution.result.duration_ms for execution in sub_test_executions
        )
        return ExecutedTest(
            definition=self.definition,
            result=TestResult(status=status, duration_ms=duration),
            test_execution_id=self.test_execution_id,
            sub_test_executions=sub_test_executions,
        )

    async def _execute_children(
        self,
        execute_child: Callable[
            [int], Coroutine[Any, Any, tuple[int, ExecutedTest]]
        ],
    ) -> list[ExecutedTest]:
        tasks = [
            asyncio.create_task(execute_child(index))
            for index in range(len(self.children))
        ]
        sub_test_executions: list[ExecutedTest | None] = [None] * len(self.children)
        try:
            for completed_task in asyncio.as_completed(tasks):
                index, sub_execution = await completed_task
                sub_test_executions[index] = sub_execution
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return [
            execution for execution in sub_test_executions if execution is not None
        ]
