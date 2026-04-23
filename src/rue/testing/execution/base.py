"""Execution base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from rue.resources.resolver import ResourceResolver
from rue.testing.models.executed import ExecutedTest
from rue.testing.models.result import TestResult, TestStatus

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

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
    node_key: str
    children: list["ExecutableTest"]
    on_complete: Callable[[ExecutedTest], Awaitable[None]] | None = None

    def walk(self) -> list["ExecutableTest"]:
        nodes: list[ExecutableTest] = [self]
        for child in self.children:
            for node in child.walk():
                nodes.append(node)
        return nodes

    def leaves(self) -> list["ExecutableTest"]:
        if not self.children:
            return [self]

        leaves: list[ExecutableTest] = []
        for child in self.children:
            for leaf in child.leaves():
                leaves.append(leaf)
        return leaves

    async def execute(self, resolver: ResourceResolver) -> ExecutedTest:
        """Execute the test and return result."""
        if self.definition.spec.definition_error:
            execution = ExecutedTest(
                definition=self.definition,
                node_key=self.node_key,
                result=TestResult(
                    status=TestStatus.ERROR,
                    duration_ms=0,
                    error=ValueError(self.definition.spec.definition_error),
                ),
                execution_id=uuid4(),
            )
        else:
            start = time.perf_counter()
            try:
                execution = await self._execute(resolver)
            except Exception as error:  # noqa: BLE001
                execution = ExecutedTest(
                    definition=self.definition,
                    node_key=self.node_key,
                    result=TestResult(
                        status=TestStatus.ERROR,
                        duration_ms=(time.perf_counter() - start) * 1000,
                        error=error,
                    ),
                    execution_id=uuid4(),
                )

        if self.on_complete is not None:
            await self.on_complete(execution)

        return execution

    @abstractmethod
    async def _execute(self, resolver: ResourceResolver) -> ExecutedTest:
        """Execute the concrete test body and return result."""
