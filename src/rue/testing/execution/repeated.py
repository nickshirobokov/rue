"""Repeated test execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from rue.context.runtime import CURRENT_RUNNER
from rue.resources import ResourceResolver
from rue.testing.execution.interfaces import Test, TestFactory
from rue.testing.models import (
    TestDefinition,
    RepeatModifier,
    TestExecution,
    TestResult,
    TestStatus,
)


@dataclass
class RepeatedTest(Test):
    """Executes test N times, aggregates results."""

    definition: TestDefinition
    params: dict[str, Any]
    count: int
    min_passes: int
    factory: TestFactory

    def __post_init__(self) -> None:
        """Validate that the first modifier is RepeatModifier."""
        if not self.definition.modifiers or not isinstance(
            self.definition.modifiers[0], RepeatModifier
        ):
            raise ValueError(
                "RepeatedTest requires RepeatModifier as first modifier"
            )

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        """Execute test count times and aggregate results."""

        async def run_child(index: int) -> tuple[int, TestExecution]:
            suffix = f"repeat={index}"
            child_def = replace(
                self.definition,
                modifiers=self.definition.modifiers[1:],
                suffix=suffix,
            )
            child = self.factory.build(child_def, self.params)
            execution = await child.execute(resolver)
            return index, execution

        tasks: list[asyncio.Task[tuple[int, TestExecution]]] = []
        for index in range(self.count):
            tasks.append(asyncio.create_task(run_child(index)))

        sub_executions: list[TestExecution | None] = [None] * self.count
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

        ordered_sub_executions = [
            execution for execution in sub_executions if execution is not None
        ]

        passed = sum(
            1
            for e in ordered_sub_executions
            if e.result.status == TestStatus.PASSED
        )
        status = (
            TestStatus.PASSED
            if passed >= self.min_passes
            else TestStatus.FAILED
        )
        duration = sum(e.result.duration_ms for e in ordered_sub_executions)

        return TestExecution(
            definition=self.definition,
            result=TestResult(status=status, duration_ms=duration),
            execution_id=uuid4(),
            sub_executions=ordered_sub_executions,
        )
