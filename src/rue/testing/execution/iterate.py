"""Iterated test execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Callable, Coroutine
from uuid import uuid4

from rue.context.runtime import CURRENT_RUNNER
from rue.resources import ResourceResolver
from rue.testing.execution.interfaces import Test, TestFactory
from rue.testing.models import (
    Case,
    CaseGroup,
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    ParameterSet,
    ParamsIterateModifier,
    TestDefinition,
    TestExecution,
    TestResult,
    TestStatus,
)


async def _run_children(
    definition: TestDefinition,
    count: int,
    run_child: Callable[[int], Coroutine[Any, Any, tuple[int, TestExecution]]],
) -> list[TestExecution]:
    tasks = [asyncio.create_task(run_child(index)) for index in range(count)]
    sub_executions: list[TestExecution | None] = [None] * count
    runner = CURRENT_RUNNER.get()
    try:
        for completed_task in asyncio.as_completed(tasks):
            index, sub_execution = await completed_task
            sub_executions[index] = sub_execution
            if runner:
                await runner.notify_subtest_complete(definition, sub_execution)
    except Exception:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return [execution for execution in sub_executions if execution is not None]


def _build_threshold_execution(
    definition: TestDefinition,
    sub_executions: list[TestExecution],
    min_passes: int,
) -> TestExecution:
    passed = sum(
        1
        for execution in sub_executions
        if execution.result.status == TestStatus.PASSED
    )
    status = TestStatus.PASSED if passed >= min_passes else TestStatus.FAILED
    duration = sum(execution.result.duration_ms for execution in sub_executions)
    return TestExecution(
        definition=definition,
        result=TestResult(status=status, duration_ms=duration),
        execution_id=uuid4(),
        sub_executions=sub_executions,
    )


@dataclass
class IterateTest(Test):
    """Executes a test N times and aggregates results."""

    definition: TestDefinition
    params: dict[str, Any]
    count: int
    min_passes: int
    factory: TestFactory

    def __post_init__(self) -> None:
        if not self.definition.modifiers or not isinstance(
            self.definition.modifiers[0], IterateModifier
        ):
            raise ValueError(
                "IterateTest requires IterateModifier as first modifier"
            )

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        async def run_child(index: int) -> tuple[int, TestExecution]:
            child_def = replace(
                self.definition,
                modifiers=self.definition.modifiers[1:],
                suffix=f"iterate={index}",
            )
            child = self.factory.build(child_def, self.params)
            execution = await child.execute(resolver)
            return index, execution

        sub_executions = await _run_children(
            self.definition,
            self.count,
            run_child,
        )
        return _build_threshold_execution(
            self.definition,
            sub_executions,
            self.min_passes,
        )


@dataclass
class ParamsIterateTest(Test):
    """Executes a test for each parameter set and aggregates results."""

    definition: TestDefinition
    params: dict[str, Any]
    parameter_sets: tuple[ParameterSet, ...]
    min_passes: int
    factory: TestFactory

    def __post_init__(self) -> None:
        if not self.definition.modifiers or not isinstance(
            self.definition.modifiers[0], ParamsIterateModifier
        ):
            raise ValueError(
                "ParamsIterateTest requires ParamsIterateModifier as first modifier"
            )

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        async def run_child(index: int) -> tuple[int, TestExecution]:
            parameter_set = self.parameter_sets[index]
            child_def = replace(
                self.definition,
                modifiers=self.definition.modifiers[1:],
                suffix=parameter_set.suffix,
            )
            child_params = {**self.params, **parameter_set.values}
            child = self.factory.build(child_def, child_params)
            execution = await child.execute(resolver)
            return index, execution

        sub_executions = await _run_children(
            self.definition,
            len(self.parameter_sets),
            run_child,
        )
        return _build_threshold_execution(
            self.definition,
            sub_executions,
            self.min_passes,
        )


@dataclass
class CasesIterateTest(Test):
    """Executes a test for each case and aggregates results."""

    definition: TestDefinition
    params: dict[str, Any]
    cases: tuple[Case[Any, Any], ...]
    min_passes: int
    factory: TestFactory

    def __post_init__(self) -> None:
        if not self.definition.modifiers or not isinstance(
            self.definition.modifiers[0], CasesIterateModifier
        ):
            raise ValueError(
                "CasesIterateTest requires CasesIterateModifier as first modifier"
            )

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        async def run_child(index: int) -> tuple[int, TestExecution]:
            case = self.cases[index]
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

        sub_executions = await _run_children(
            self.definition,
            len(self.cases),
            run_child,
        )
        return _build_threshold_execution(
            self.definition,
            sub_executions,
            self.min_passes,
        )


@dataclass
class GroupsIterateTest(Test):
    """Executes a test for each case group and aggregates results."""

    definition: TestDefinition
    params: dict[str, Any]
    groups: tuple[CaseGroup[Any, Any, Any], ...]
    min_passes: int
    factory: TestFactory

    def __post_init__(self) -> None:
        if not self.definition.modifiers or not isinstance(
            self.definition.modifiers[0], GroupsIterateModifier
        ):
            raise ValueError(
                "GroupsIterateTest requires GroupsIterateModifier as first modifier"
            )

    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        async def run_child(index: int) -> tuple[int, TestExecution]:
            group = self.groups[index]
            child_def = replace(
                self.definition,
                modifiers=[
                    CasesIterateModifier(
                        cases=tuple(group.cases),
                        min_passes=group.min_passes,
                    ),
                    *self.definition.modifiers[1:],
                ],
                suffix=group.name,
            )
            child_params = {**self.params, "group": group}
            child = self.factory.build(child_def, child_params)
            execution = await child.execute(resolver)
            return index, execution

        sub_executions = await _run_children(
            self.definition,
            len(self.groups),
            run_child,
        )
        return _build_threshold_execution(
            self.definition,
            sub_executions,
            self.min_passes,
        )


__all__ = [
    "CasesIterateTest",
    "GroupsIterateTest",
    "IterateTest",
    "ParamsIterateTest",
]
