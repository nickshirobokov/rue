"""Session-level forwarding for run lifecycle events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cloudpickle  # type: ignore[import-untyped]

from rue.context.runtime import CURRENT_RUN_CONTEXT, RunContext
from rue.events.processor import RunEventsProcessor


if TYPE_CHECKING:
    from rue.config import Config
    from rue.resources.models import ResourceGraph
    from rue.testing import LoadedTestDef
    from rue.testing.execution.executable.base import ExecutableTest
    from rue.testing.models import ExecutedRun, ExecutedTest


@dataclass(frozen=True, slots=True)
class _QueuedRunEvent:
    method_name: str
    args: tuple[Any, ...]
    context: RunContext


class QueueForwarder(RunEventsProcessor):
    """Forward run events to another process through a queue."""

    def __init__(self, queue: Any) -> None:
        self._queue = queue

    async def on_run_start(self, run: ExecutedRun) -> None:
        """Forward run start."""
        self._put("on_run_start", run)

    async def on_no_tests_found(self, run: ExecutedRun) -> None:
        """Forward empty collection."""
        self._put("on_no_tests_found", run)

    async def on_collection_complete(
        self, items: list[LoadedTestDef], run: ExecutedRun
    ) -> None:
        """Forward collection completion."""
        self._put("on_collection_complete", items, run)

    async def on_tests_ready(
        self, tests: list[ExecutableTest], run: ExecutedRun
    ) -> None:
        """Forward executable test readiness."""
        self._put("on_tests_ready", tests, run)

    async def on_di_graphs_compiled(
        self, graphs: dict[Any, ResourceGraph]
    ) -> None:
        """Forward dependency graph compilation."""
        self._put("on_di_graphs_compiled", graphs)

    async def on_test_start(
        self, test: ExecutableTest, run: ExecutedRun
    ) -> None:
        """Forward test start."""
        self._put("on_test_start", test, run)

    async def on_execution_complete(
        self, execution: ExecutedTest, run: ExecutedRun
    ) -> None:
        """Forward execution completion."""
        self._put("on_execution_complete", execution, run)

    async def on_run_stopped_early(
        self, failure_count: int, run: ExecutedRun
    ) -> None:
        """Forward early run stop."""
        self._put("on_run_stopped_early", failure_count, run)

    async def on_run_complete(self, run: ExecutedRun) -> None:
        """Forward run completion."""
        self._put("on_run_complete", run)

    def close(self) -> None:
        """Signal that this run will not emit more events."""
        self._queue.put(None)

    def _put(self, method_name: str, *args: Any) -> None:
        event = _QueuedRunEvent(
            method_name=method_name,
            args=args,
            context=CURRENT_RUN_CONTEXT.get(),
        )
        self._queue.put(cloudpickle.dumps(event))


class SessionEventsReceiver(RunEventsProcessor):
    """Receives events from one or more runs and forwards to processors."""

    def __init__(self, processors: list[RunEventsProcessor]) -> None:
        self.processors = tuple(processors)
        self._closed = False

    def configure(self, config: Config) -> None:
        """Apply runtime configuration to session processors."""
        for processor in self.processors:
            processor.configure(config)

    async def on_run_start(self, run: ExecutedRun) -> None:
        """Called when a child run starts."""
        await self._emit("on_run_start", run)

    async def on_no_tests_found(self, run: ExecutedRun) -> None:
        """Called when a child run has no tests."""
        await self._emit("on_no_tests_found", run)

    async def on_collection_complete(
        self, items: list[LoadedTestDef], run: ExecutedRun
    ) -> None:
        """Called after child run collection completes."""
        await self._emit("on_collection_complete", items, run)

    async def on_tests_ready(
        self, tests: list[ExecutableTest], run: ExecutedRun
    ) -> None:
        """Called after a child run builds executable tests."""
        await self._emit("on_tests_ready", tests, run)

    async def on_di_graphs_compiled(
        self, graphs: dict[Any, ResourceGraph]
    ) -> None:
        """Called after a child run compiles dependency graphs."""
        await self._emit("on_di_graphs_compiled", graphs)

    async def on_test_start(
        self, test: ExecutableTest, run: ExecutedRun
    ) -> None:
        """Called before a child run starts a test."""
        await self._emit("on_test_start", test, run)

    async def on_execution_complete(
        self, execution: ExecutedTest, run: ExecutedRun
    ) -> None:
        """Called when a child run execution completes."""
        await self._emit("on_execution_complete", execution, run)

    async def on_run_stopped_early(
        self, failure_count: int, run: ExecutedRun
    ) -> None:
        """Called when a child run stops early."""
        await self._emit("on_run_stopped_early", failure_count, run)

    async def on_run_complete(self, run: ExecutedRun) -> None:
        """Called after a child run completes."""
        await self._emit("on_run_complete", run)

    async def drain_queue(self, queue: Any) -> None:
        """Drain forwarded run events until the queue sentinel arrives."""
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
