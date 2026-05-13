"""Base processor for suite lifecycle events."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID


if TYPE_CHECKING:
    from rue.config import Config
    from rue.resources.models import ResourceGraph
    from rue.testing.execution.suite.models import ExecutedSuite
    from rue.testing.execution.test.base import ExecutableTest
    from rue.testing.execution.test.models import ExecutedTest, LoadedTestDef


class SuiteEventsProcessorMeta(type):
    """Registers processor instances after initialization."""

    def __call__(cls, *args: Any, **kwargs: Any) -> SuiteEventsProcessor:
        """Create and register a suite event processor."""
        processor = super().__call__(*args, **kwargs)
        if cls is not SuiteEventsProcessor and not cls.__module__.startswith(
            "rue."
        ):
            SuiteEventsProcessor.REGISTRY[cls.__name__] = processor
        return processor


class SuiteEventsProcessor(metaclass=SuiteEventsProcessorMeta):
    """Base class for suite lifecycle event processors."""

    REGISTRY: ClassVar[dict[str, SuiteEventsProcessor]] = {}

    def configure(self, config: Config) -> None:
        """Adjust processor parameters based on runtime config."""
        _ = config

    async def on_suite_execution_start(
        self, suite: ExecutedSuite
    ) -> None:
        """Called when suite execution starts."""
        _ = suite
        return None

    async def on_no_tests_found(self, suite: ExecutedSuite) -> None:
        """Called when test collection finds no tests."""
        _ = suite
        return None

    async def on_collection_complete(
        self, items: list[LoadedTestDef], suite: ExecutedSuite
    ) -> None:
        """Called after test collection completes."""
        _ = items, suite
        return None

    async def on_tests_ready(
        self, tests: list[ExecutableTest], suite: ExecutedSuite
    ) -> None:
        """Called after all executable test trees are built."""
        _ = tests, suite
        return None

    async def on_di_graphs_compiled(
        self, graphs: dict[UUID, ResourceGraph]
    ) -> None:
        """Called after dependency injection graphs are compiled."""
        _ = graphs
        return None

    async def on_test_execution_start(
        self, test: ExecutableTest, suite: ExecutedSuite
    ) -> None:
        """Called before test execution starts."""
        _ = test, suite
        return None

    async def on_test_execution_complete(
        self, execution: ExecutedTest, suite: ExecutedSuite
    ) -> None:
        """Called when any test execution node completes."""
        _ = execution, suite
        return None

    async def on_suite_stopped_early(
        self, failure_count: int, suite: ExecutedSuite
    ) -> None:
        """Called when suite stops early due to maxfail limit."""
        _ = failure_count, suite
        return None

    async def on_suite_execution_complete(
        self, suite: ExecutedSuite
    ) -> None:
        """Called after suite execution completes."""
        _ = suite
        return None

    def close(self) -> None:
        """Release processor resources."""
        return None
