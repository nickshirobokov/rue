"""Context receiver for run lifecycle events."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from types import TracebackType
from typing import TYPE_CHECKING
from uuid import UUID

from rue.events.processor import RunEventsProcessor


if TYPE_CHECKING:
    from rue.config import Config
    from rue.resources.models import ResourceGraph
    from rue.testing import LoadedTestDef
    from rue.testing.execution.base import ExecutableTest
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import Run


class RunEventsReceiver:
    """Receives run events and forwards them to attached processors."""

    def __init__(self, processors: list[RunEventsProcessor]) -> None:
        self.processors = processors
        self._tokens: list[Token[RunEventsReceiver]] = []

    @classmethod
    def current(cls) -> RunEventsReceiver:
        """Return the receiver bound to the current execution scope."""
        return CURRENT_RUN_EVENTS_RECEIVER.get()

    def __enter__(self) -> RunEventsReceiver:
        """Bind this receiver to the current execution scope."""
        self._tokens.append(CURRENT_RUN_EVENTS_RECEIVER.set(self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous run events receiver."""
        CURRENT_RUN_EVENTS_RECEIVER.reset(self._tokens.pop())

    def configure(self, config: Config) -> None:
        """Adjust processor parameters based on runtime config."""
        for processor in self.processors:
            processor.configure(config)

    async def on_run_start(self, run: Run) -> None:
        """Called when a run starts."""
        await asyncio.gather(
            *[processor.on_run_start(run) for processor in self.processors]
        )

    async def on_no_tests_found(self, run: Run) -> None:
        """Called when test collection finds no tests."""
        await asyncio.gather(
            *[
                processor.on_no_tests_found(run)
                for processor in self.processors
            ]
        )

    async def on_collection_complete(
        self, items: list[LoadedTestDef], run: Run
    ) -> None:
        """Called after test collection completes."""
        await asyncio.gather(
            *[
                processor.on_collection_complete(items, run)
                for processor in self.processors
            ]
        )

    async def on_tests_ready(
        self, tests: list[ExecutableTest], run: Run
    ) -> None:
        """Called after all executable test trees are built."""
        await asyncio.gather(
            *[
                processor.on_tests_ready(tests, run)
                for processor in self.processors
            ]
        )

    async def on_di_graphs_compiled(
        self, graphs: dict[UUID, ResourceGraph]
    ) -> None:
        """Called after dependency injection graphs are compiled."""
        await asyncio.gather(
            *[
                processor.on_di_graphs_compiled(graphs)
                for processor in self.processors
            ]
        )

    async def on_test_start(
        self, test: ExecutableTest, run: Run
    ) -> None:
        """Called before a test starts executing."""
        await asyncio.gather(
            *[
                processor.on_test_start(test, run)
                for processor in self.processors
            ]
        )

    async def on_execution_complete(
        self, execution: ExecutedTest, run: Run
    ) -> None:
        """Called when any test node completes."""
        await asyncio.gather(
            *[
                processor.on_execution_complete(execution, run)
                for processor in self.processors
            ]
        )

    async def on_run_stopped_early(
        self, failure_count: int, run: Run
    ) -> None:
        """Called when run stops early due to maxfail limit."""
        await asyncio.gather(
            *[
                processor.on_run_stopped_early(failure_count, run)
                for processor in self.processors
            ]
        )

    async def on_run_complete(self, run: Run) -> None:
        """Called after all tests complete."""
        await asyncio.gather(
            *[processor.on_run_complete(run) for processor in self.processors]
        )


CURRENT_RUN_EVENTS_RECEIVER: ContextVar[RunEventsReceiver] = ContextVar(
    "current_run_events_receiver"
)
