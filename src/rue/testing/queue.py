"""Execution queue for runner-owned test scheduling."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from rue.testing.execution.interfaces import ExecutableTest
from rue.testing.execution.types import ExecutionBackend
from rue.testing.models.executed import ExecutedTest
from rue.testing.models.loaded import LoadedTestDef


@dataclass(slots=True)
class RunnerStep:
    """One runner scheduling step."""

    is_main: bool
    tests: list[ExecutableTest] = field(default_factory=list)
    _lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )
    _results: list[ExecutedTest | None] = field(
        default_factory=list, init=False, repr=False
    )
    _next_index: int = field(default=0, init=False, repr=False)
    _next_result_index: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._results = [None] * len(self.tests)

    def append(self, test: ExecutableTest) -> None:
        """Append a test to this step."""
        self.tests.append(test)
        self._results.append(None)

    def worker_count(self, concurrency_limit: int) -> int:
        """Return the number of workers needed for this step."""
        return min(concurrency_limit, len(self.tests))

    async def dequeue(
        self,
        *,
        is_stopped: Callable[[], bool],
        on_test_start: Callable[[LoadedTestDef], Awaitable[None]],
    ) -> tuple[int, ExecutableTest] | None:
        """Return the next queued test in stable order."""
        async with self._lock:
            if is_stopped() or self._next_index >= len(self.tests):
                return None
            index = self._next_index
            self._next_index += 1
            test = self.tests[index]
            await on_test_start(test.definition)
            return index, test

    async def record(
        self,
        index: int,
        execution: ExecutedTest,
        *,
        on_ready: Callable[[ExecutedTest], None],
    ) -> None:
        """Store a completed execution and flush ready results in order."""
        async with self._lock:
            self._results[index] = execution
            while self._next_result_index < len(self._results):
                ready = self._results[self._next_result_index]
                if ready is None:
                    break
                on_ready(ready)
                self._next_result_index += 1


@dataclass(slots=True)
class TestQueue:
    """Ordered queue of backend-aware runner steps."""

    steps: list[RunnerStep] = field(default_factory=list)

    def add(self, test: ExecutableTest) -> None:
        """Append a top-level executable test to the queue."""
        is_main = test.backend is ExecutionBackend.MAIN
        if self.steps and self.steps[-1].is_main == is_main:
            self.steps[-1].append(test)
            return
        self.steps.append(RunnerStep(is_main=is_main, tests=[test]))

    @property
    def tests(self) -> list[ExecutableTest]:
        """Flattened top-level executable tests in queue order."""
        return [test for step in self.steps for test in step.tests]
