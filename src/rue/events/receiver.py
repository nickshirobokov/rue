"""Context receiver for suite lifecycle events."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from types import TracebackType
from typing import TYPE_CHECKING
from uuid import UUID

from rue.context.runtime import SUITE_EXECUTION_CONTEXT
from rue.events.processor import SuiteEventsProcessor


if TYPE_CHECKING:
    from rue.resources.models import ResourceGraph
    from rue.testing.execution.suite.models import ExecutedSuite
    from rue.testing.execution.test.base import ExecutableTest
    from rue.testing.execution.test.models import ExecutedTest, LoadedTestDef


class SuiteEventsReceiver:
    """Receives suite events and forwards them to attached processors."""

    suite: ExecutedSuite

    def __init__(self, processors: list[SuiteEventsProcessor]) -> None:
        if not processors:
            raise ValueError(
                "SuiteEventsReceiver requires at least one processor"
            )
        self.processors = tuple(processors)
        self._tokens: list[Token[SuiteEventsReceiver]] = []

    @classmethod
    def current(cls) -> SuiteEventsReceiver:
        """Return the receiver bound to the current suite execution scope."""
        return CURRENT_SUITE_EVENTS_RECEIVER.get()

    def __enter__(self) -> SuiteEventsReceiver:
        """Bind this receiver to the current suite execution scope."""
        config = SUITE_EXECUTION_CONTEXT.get().config
        for processor in self.processors:
            processor.configure(config)
        self._tokens.append(CURRENT_SUITE_EVENTS_RECEIVER.set(self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous suite events receiver."""
        for processor in self.processors:
            processor.close()
        CURRENT_SUITE_EVENTS_RECEIVER.reset(self._tokens.pop())

    async def on_suite_execution_start(self, suite: ExecutedSuite) -> None:
        """Called when suite execution starts."""
        self.suite = suite
        await asyncio.gather(
            *(
                processor.on_suite_execution_start(suite)
                for processor in self.processors
            )
        )

    async def on_no_tests_found(self) -> None:
        """Called when test collection finds no tests."""
        await asyncio.gather(
            *(
                processor.on_no_tests_found(self.suite)
                for processor in self.processors
            )
        )

    async def on_collection_complete(
        self, items: list[LoadedTestDef]
    ) -> None:
        """Called after test collection completes."""
        await asyncio.gather(
            *(
                processor.on_collection_complete(items, self.suite)
                for processor in self.processors
            )
        )

    async def on_tests_ready(
        self, tests: list[ExecutableTest]
    ) -> None:
        """Called after all executable test trees are built."""
        await asyncio.gather(
            *(
                processor.on_tests_ready(tests, self.suite)
                for processor in self.processors
            )
        )

    async def on_di_graphs_compiled(
        self, graphs: dict[UUID, ResourceGraph]
    ) -> None:
        """Called after dependency injection graphs are compiled."""
        await asyncio.gather(
            *(
                processor.on_di_graphs_compiled(graphs)
                for processor in self.processors
            )
        )

    async def on_test_execution_start(
        self, test: ExecutableTest
    ) -> None:
        """Called before test execution starts."""
        await asyncio.gather(
            *(
                processor.on_test_execution_start(test, self.suite)
                for processor in self.processors
            )
        )

    async def on_test_execution_complete(
        self, execution: ExecutedTest
    ) -> None:
        """Called when any test execution node completes."""
        await asyncio.gather(
            *(
                processor.on_test_execution_complete(execution, self.suite)
                for processor in self.processors
            )
        )

    async def on_suite_stopped_early(
        self, failure_count: int
    ) -> None:
        """Called when suite stops early due to maxfail limit."""
        await asyncio.gather(
            *(
                processor.on_suite_stopped_early(
                    failure_count,
                    self.suite,
                )
                for processor in self.processors
            )
        )

    async def on_suite_execution_complete(self) -> None:
        """Called after suite execution completes."""
        await asyncio.gather(
            *(
                processor.on_suite_execution_complete(self.suite)
                for processor in self.processors
            )
        )


CURRENT_SUITE_EVENTS_RECEIVER: ContextVar[SuiteEventsReceiver] = ContextVar(
    "current_suite_events_receiver"
)
