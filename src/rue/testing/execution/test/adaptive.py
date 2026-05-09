"""Adaptive execution driven by a case factory."""

from __future__ import annotations

from dataclasses import dataclass, field
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
from rue.testing.models.case import CaseFactory


@dataclass(kw_only=True)
class AdaptiveTest(ExecutableTest):
    """Executes prebuilt attempt slots with cases from a factory."""

    definition: LoadedTestDef
    backend: ExecutionBackend
    min_passes: int
    test_execution_id: UUID
    factory: CaseFactory
    children: list[ExecutableTest] = field(default_factory=list)

    async def _execute(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        sub_test_executions: list[ExecutedTest] = []

        for child in self.children:
            case = await self.factory.next_case(self.definition)
            if case is None:
                break

            for leaf in child.leaves():
                leaf.params["case"] = case
                leaf.definition.spec.case_id = case.id

            execution = await child.execute(resolver)
            sub_test_executions.append(execution)
            await self.factory.observe(case, execution)
            if execution.result.status.is_failure:
                break


        if len(sub_test_executions) < len(self.children):
            reason = (
                "case factory stopped after failing attempt"
                if (
                    sub_test_executions
                    and sub_test_executions[-1].result.status.is_failure
                )
                else "case factory exhausted"
            )
            for child in self.children[len(sub_test_executions) :]:
                execution = await child.not_run(reason)
                sub_test_executions.append(execution)

        duration = sum(
            execution.result.duration_ms for execution in sub_test_executions
        )
        executed = [
            execution
            for execution in sub_test_executions
            if execution.result.status is not TestStatus.NOT_RUN
        ]
        status = TestStatus.FAILED
        if not executed:
            status = TestStatus.NOT_RUN
        elif any(
            execution.result.status is TestStatus.ERROR
            for execution in executed
        ):
            status = TestStatus.ERROR
        elif any(
            execution.result.status.is_failure for execution in executed
        ):
            status = TestStatus.FAILED
        elif all(
            execution.result.status is TestStatus.PASSED
            for execution in executed
        ):
            status = TestStatus.PASSED

        return ExecutedTest(
            definition=self.definition,
            result=TestResult(
                status=status,
                duration_ms=duration,
            ),
            test_execution_id=self.test_execution_id,
            sub_test_executions=sub_test_executions,
        )
