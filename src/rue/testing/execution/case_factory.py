"""Case factory-backed execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from rue.resources.resolver import DependencyResolver
from rue.testing.execution.backend import ExecutionBackend
from rue.testing.execution.executable import ExecutableTest
from rue.testing.models.case import CaseFactory
from rue.testing.models.executed import ExecutedTest
from rue.testing.models.loaded import LoadedTestDef
from rue.testing.models.result import TestResult, TestStatus


@dataclass(kw_only=True)
class CaseFactoryTest(ExecutableTest):
    """Executes prebuilt attempt slots with cases from a factory."""

    definition: LoadedTestDef
    backend: ExecutionBackend
    min_passes: int
    execution_id: UUID
    factory: CaseFactory
    children: list[ExecutableTest] = field(default_factory=list)

    async def _execute(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        sub_executions: list[ExecutedTest] = []

        for child in self.children:
            case = await self.factory.next_case()
            if case is None:
                break

            for leaf in child.leaves():
                leaf.params["case"] = case
                leaf.definition.spec.case_id = case.id

            execution = await child.execute(resolver)
            sub_executions.append(execution)
            await self.factory.observe(case, execution)
            if execution.status.is_failure:
                break

        if len(sub_executions) < len(self.children):
            reason = (
                "case factory stopped after failing attempt"
                if sub_executions and sub_executions[-1].status.is_failure
                else "case factory exhausted"
            )
            for child in self.children[len(sub_executions) :]:
                execution = await child.not_run(reason)
                sub_executions.append(execution)

        duration = sum(
            execution.result.duration_ms for execution in sub_executions
        )
        executed = [
            execution
            for execution in sub_executions
            if execution.status is not TestStatus.NOT_RUN
        ]
        status = TestStatus.FAILED
        if not executed:
            status = TestStatus.NOT_RUN
        elif any(
            execution.status is TestStatus.ERROR for execution in executed
        ):
            status = TestStatus.ERROR
        elif any(execution.status.is_failure for execution in executed):
            status = TestStatus.FAILED
        elif all(
            execution.status is TestStatus.PASSED for execution in executed
        ):
            status = TestStatus.PASSED

        return ExecutedTest(
            definition=self.definition,
            result=TestResult(
                status=status,
                duration_ms=duration,
            ),
            execution_id=self.execution_id,
            sub_executions=sub_executions,
        )
