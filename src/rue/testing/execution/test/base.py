"""Executable test base classes."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

from rue.events import SuiteEventsReceiver
from rue.resources.resolver import DependencyResolver
from rue.testing.execution.backend import ExecutionBackend
from rue.testing.execution.test.models import (
    ExecutedTest,
    TestResult,
    TestStatus,
)


if TYPE_CHECKING:
    from rue.testing.execution.test.models import LoadedTestDef
    from rue.testing.execution.test.single import SingleTest


class ExecutableTest(ABC):
    """Executable test - single or composite."""

    definition: LoadedTestDef
    backend: ExecutionBackend
    test_execution_id: UUID
    children: list[ExecutableTest]

    def walk(self) -> list[ExecutableTest]:
        """Return this test execution node and every descendant."""
        nodes: list[ExecutableTest] = [self]
        for child in self.children:
            for node in child.walk():
                nodes.append(node)
        return nodes

    def leaves(self) -> list[SingleTest]:
        """Return single-test leaves below this node."""
        from rue.testing.execution.test.single import SingleTest  # noqa: I001, PLC0415

        if not self.children:
            if not isinstance(self, SingleTest):
                raise TypeError(
                    "ExecutableTest leaves must be SingleTest instances"
                )
            return [self]

        leaves: list[SingleTest] = []
        for child in self.children:
            leaves.extend(child.leaves())
        return leaves

    async def not_run(self, reason: str) -> ExecutedTest:
        """Build and emit a synthetic result for a node that never ran."""
        sub_test_executions = [
            await child.not_run(reason) for child in self.children
        ]
        execution = ExecutedTest(
            definition=self.definition,
            result=TestResult(
                status=TestStatus.NOT_RUN,
                duration_ms=0,
                error=Exception(reason),
            ),
            test_execution_id=self.test_execution_id,
            sub_test_executions=sub_test_executions,
        )
        await SuiteEventsReceiver.current().on_test_execution_complete(execution)
        return execution

    async def execute(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        """Execute the test and return result."""
        start = time.perf_counter()
        try:
            execution = await self._execute(resolver)
        except Exception as error:
            execution = ExecutedTest(
                definition=self.definition,
                result=TestResult(
                    status=TestStatus.ERROR,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    error=error,
                ),
                test_execution_id=self.test_execution_id,
            )

        await SuiteEventsReceiver.current().on_test_execution_complete(execution)
        return execution

    @abstractmethod
    async def _execute(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        """Execute the concrete test body and return result."""
