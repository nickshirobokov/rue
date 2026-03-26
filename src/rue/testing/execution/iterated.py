"""Iterated test execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from rue.context import get_runner
from rue.resources import ResourceResolver
from rue.testing.execution.interfaces import Test, TestFactory
from rue.testing.models import (
    Case,
    CaseGroup,
    CaseGroupIterateModifier,
    CaseIterateModifier,
    TestDefinition,
    TestExecution,
    TestResult,
    TestStatus,
)


@dataclass
class CaseIteratedTest(Test):
    """Executes test for each case, aggregates results."""

    definition: TestDefinition
    params: dict[str, Any]
    cases: tuple[Case[Any, Any], ...]
    min_passes: int
    factory: TestFactory

    def __post_init__(self) -> None:
        """Validate that the first modifier is CaseIterateModifier."""
        if not self.definition.modifiers or not isinstance(
            self.definition.modifiers[0], CaseIterateModifier
        ):
            raise ValueError(
                "CaseIteratedTest requires CaseIterateModifier as first modifier"
            )

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        """Execute test for each case and aggregate results."""

        async def run_child(
            index: int, case: Case[Any, Any]
        ) -> tuple[int, TestExecution]:
            child_def = replace(
                self.definition,
                modifiers=self.definition.modifiers[1:],
                suffix=repr(case.metadata) if case.metadata else None,
                case_id=case.id,
            )
            child_params = {**self.params, "case": case}
            child = self.factory.build(child_def, child_params)
            execution = await child.execute(resolver)
            return index, execution

        tasks: list[asyncio.Task[tuple[int, TestExecution]]] = []
        for index, case in enumerate(self.cases):
            tasks.append(asyncio.create_task(run_child(index, case)))

        sub_executions: list[TestExecution | None] = [None] * len(self.cases)
        runner = get_runner()
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


@dataclass
class CaseGroupIteratedTest(Test):
    """Executes test for each case group, delegates inner case iteration."""

    definition: TestDefinition
    params: dict[str, Any]
    groups: tuple[CaseGroup[Any, Any, Any], ...]
    factory: TestFactory

    def __post_init__(self) -> None:
        """Validate that the first modifier is CaseGroupIterateModifier."""
        if not self.definition.modifiers or not isinstance(
            self.definition.modifiers[0], CaseGroupIterateModifier
        ):
            raise ValueError(
                "CaseGroupIteratedTest requires CaseGroupIterateModifier as first modifier"
            )

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        """Execute each group as a nested case-iterated child."""

        async def run_child(
            index: int, group: CaseGroup[Any, Any, Any]
        ) -> tuple[int, TestExecution]:
            child_def = replace(
                self.definition,
                modifiers=[
                    CaseIterateModifier(
                        cases=tuple(group.cases), min_passes=group.min_passes
                    ),
                    *self.definition.modifiers[1:],
                ],
                suffix=group.name,
            )
            child_params = {**self.params, "group": group}
            child = self.factory.build(child_def, child_params)
            execution = await child.execute(resolver)
            return index, execution

        tasks: list[asyncio.Task[tuple[int, TestExecution]]] = []
        for index, group in enumerate(self.groups):
            tasks.append(asyncio.create_task(run_child(index, group)))

        sub_executions: list[TestExecution | None] = [None] * len(self.groups)
        runner = get_runner()
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

        all_groups_passed = all(
            e.result.status == TestStatus.PASSED for e in ordered_sub_executions
        )
        status = TestStatus.PASSED if all_groups_passed else TestStatus.FAILED
        duration = sum(e.result.duration_ms for e in ordered_sub_executions)

        return TestExecution(
            definition=self.definition,
            result=TestResult(status=status, duration_ms=duration),
            execution_id=uuid4(),
            sub_executions=ordered_sub_executions,
        )


CaseIteratedRueTest = CaseIteratedTest
CaseGroupIteratedRueTest = CaseGroupIteratedTest
