"""Execution base classes."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from rue.events import RunEventsReceiver
from rue.resources.resolver import DependencyResolver
from rue.testing.models.executed import ExecutedTest
from rue.testing.models.result import TestResult, TestStatus


if TYPE_CHECKING:
    from rue.testing.models.loaded import LoadedTestDef


class ExecutionBackend(StrEnum):
    """Where a test node runs."""

    MAIN = "main"
    MODULE_MAIN = "module_main"
    ASYNCIO = "asyncio"
    SUBPROCESS = "subprocess"


class ExecutableTest(ABC):
    """Executable test - single or composite."""

    definition: LoadedTestDef
    backend: ExecutionBackend
    execution_id: UUID
    children: list[ExecutableTest]

    def walk(self) -> list[ExecutableTest]:
        """Return this execution node and every descendant."""
        nodes: list[ExecutableTest] = [self]
        for child in self.children:
            for node in child.walk():
                nodes.append(node)
        return nodes

    def leaves(self) -> list[ExecutableTest]:
        """Return executable leaves below this node."""
        if not self.children:
            return [self]

        leaves: list[ExecutableTest] = []
        for child in self.children:
            for leaf in child.leaves():
                leaves.append(leaf)
        return leaves

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
                execution_id=self.execution_id,
            )

        await RunEventsReceiver.current().on_execution_complete(execution)
        return execution

    @abstractmethod
    async def _execute(
        self,
        resolver: DependencyResolver,
    ) -> ExecutedTest:
        """Execute the concrete test body and return result."""
