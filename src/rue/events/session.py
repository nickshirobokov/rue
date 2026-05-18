"""Session-level forwarding for suite lifecycle events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cloudpickle  # type: ignore[import-untyped]

from rue.context.runtime import SUITE_EXECUTION_CONTEXT, SuiteContext
from rue.events.processor import SuiteEventsProcessor


if TYPE_CHECKING:
    from rue.config import Config
    from rue.resources.models import ResourceGraph
    from rue.testing.execution.suite.models import ExecutedSuite
    from rue.testing.execution.test.base import ExecutableTest
    from rue.testing.execution.test.models import ExecutedTest, LoadedTestDef


@dataclass(frozen=True, slots=True)
class _QueuedSuiteEvent:
    method_name: str
    args: tuple[Any, ...]
    context: SuiteContext


class QueueForwarder(SuiteEventsProcessor):
    """Forward suite events to another process through a queue."""

    def __init__(self, queue: Any) -> None:
        self._queue = queue

    async def on_suite_execution_start(self, suite: ExecutedSuite) -> None:
        """Forward suite execution start."""
        self._put("on_suite_execution_start", suite)

    async def on_no_tests_found(self, suite: ExecutedSuite) -> None:
        """Forward empty collection."""
        self._put("on_no_tests_found", suite)

    async def on_collection_complete(
        self, items: list[LoadedTestDef], suite: ExecutedSuite
    ) -> None:
        """Forward collection completion."""
        self._put("on_collection_complete", items, suite)

    async def on_tests_ready(
        self, tests: list[ExecutableTest], suite: ExecutedSuite
    ) -> None:
        """Forward executable test readiness."""
        self._put("on_tests_ready", tests, suite)

    async def on_di_graphs_compiled(
        self, graphs: dict[Any, ResourceGraph]
    ) -> None:
        """Forward dependency graph compilation."""
        self._put("on_di_graphs_compiled", graphs)

    async def on_test_execution_start(
        self, test: ExecutableTest, suite: ExecutedSuite
    ) -> None:
        """Forward test execution start."""
        self._put("on_test_execution_start", test, suite)

    async def on_test_execution_complete(
        self, execution: ExecutedTest, suite: ExecutedSuite
    ) -> None:
        """Forward test execution completion."""
        self._put("on_test_execution_complete", execution, suite)

    async def on_suite_stopped_early(
        self, failure_count: int, suite: ExecutedSuite
    ) -> None:
        """Forward early suite stop."""
        self._put("on_suite_stopped_early", failure_count, suite)

    async def on_suite_execution_complete(self, suite: ExecutedSuite) -> None:
        """Forward suite execution completion."""
        self._put("on_suite_execution_complete", suite)

    def close(self) -> None:
        """Signal that this suite will not emit more events."""
        self._queue.put(None)

    def _put(self, method_name: str, *args: Any) -> None:
        event = _QueuedSuiteEvent(
            method_name=method_name,
            args=args,
            context=SUITE_EXECUTION_CONTEXT.get(),
        )
        self._queue.put(cloudpickle.dumps(event))


class SessionEventsReceiver(SuiteEventsProcessor):
    """Receives events from one or more suites and forwards to processors."""

    def __init__(self, processors: list[SuiteEventsProcessor]) -> None:
        self.processors = tuple(processors)
        self._closed = False

    def configure(self, config: Config) -> None:
        """Apply runtime configuration to session processors."""
        for processor in self.processors:
            processor.configure(config)

    async def on_suite_execution_start(self, suite: ExecutedSuite) -> None:
        """Called when child suite execution starts."""
        await self._emit("on_suite_execution_start", suite)

    async def on_no_tests_found(self, suite: ExecutedSuite) -> None:
        """Called when a child suite has no tests."""
        await self._emit("on_no_tests_found", suite)

    async def on_collection_complete(
        self, items: list[LoadedTestDef], suite: ExecutedSuite
    ) -> None:
        """Called after child suite collection completes."""
        await self._emit("on_collection_complete", items, suite)

    async def on_tests_ready(
        self, tests: list[ExecutableTest], suite: ExecutedSuite
    ) -> None:
        """Called after a child suite builds executable tests."""
        await self._emit("on_tests_ready", tests, suite)

    async def on_di_graphs_compiled(
        self, graphs: dict[Any, ResourceGraph]
    ) -> None:
        """Called after a child suite compiles dependency graphs."""
        await self._emit("on_di_graphs_compiled", graphs)

    async def on_test_execution_start(
        self, test: ExecutableTest, suite: ExecutedSuite
    ) -> None:
        """Called before a child suite starts test execution."""
        await self._emit("on_test_execution_start", test, suite)

    async def on_test_execution_complete(
        self, execution: ExecutedTest, suite: ExecutedSuite
    ) -> None:
        """Called when a child suite test execution completes."""
        await self._emit("on_test_execution_complete", execution, suite)

    async def on_suite_stopped_early(
        self, failure_count: int, suite: ExecutedSuite
    ) -> None:
        """Called when a child suite stops early."""
        await self._emit("on_suite_stopped_early", failure_count, suite)

    async def on_suite_execution_complete(self, suite: ExecutedSuite) -> None:
        """Called after child suite execution completes."""
        await self._emit("on_suite_execution_complete", suite)

    async def drain_queue(self, queue: Any) -> None:
        """Drain forwarded suite events until the queue sentinel arrives."""
        while payload := await asyncio.to_thread(queue.get):
            event = cloudpickle.loads(payload)
            with event.context:
                await getattr(self, event.method_name)(*event.args)

    def close(self) -> None:
        """Release session processor resources."""
        if self._closed:
            return
        for processor in self.processors:
            processor.close()
        self._closed = True

    async def _emit(self, method_name: str, *args: Any) -> None:
        await asyncio.gather(
            *(
                getattr(processor, method_name)(*args)
                for processor in self.processors
            )
        )
