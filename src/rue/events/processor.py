"""Base processor for run lifecycle events."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID


if TYPE_CHECKING:
    from rue.config import Config
    from rue.resources.models import ResourceGraph
    from rue.testing import LoadedTestDef
    from rue.testing.execution.executable import ExecutableTest
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import ExecutedRun


class RunEventsProcessorMeta(type):
    """Registers processor instances after initialization."""

    def __call__(cls, *args: Any, **kwargs: Any) -> RunEventsProcessor:
        """Create and register a run event processor."""
        processor = super().__call__(*args, **kwargs)
        if cls is not RunEventsProcessor and not cls.__module__.startswith(
            "rue."
        ):
            RunEventsProcessor.REGISTRY[cls.__name__] = processor
        return processor


class RunEventsProcessor(metaclass=RunEventsProcessorMeta):
    """Base class for run lifecycle event processors."""

    REGISTRY: ClassVar[dict[str, RunEventsProcessor]] = {}

    def configure(self, config: Config) -> None:
        """Adjust processor parameters based on runtime config."""
        _ = config

    async def on_run_start(self, run: ExecutedRun) -> None:
        """Called when a run starts."""
        _ = run
        return None

    async def on_no_tests_found(self, run: ExecutedRun) -> None:
        """Called when test collection finds no tests."""
        _ = run
        return None

    async def on_collection_complete(
        self, items: list[LoadedTestDef], run: ExecutedRun
    ) -> None:
        """Called after test collection completes."""
        _ = items, run
        return None

    async def on_tests_ready(
        self, tests: list[ExecutableTest], run: ExecutedRun
    ) -> None:
        """Called after all executable test trees are built."""
        _ = tests, run
        return None

    async def on_di_graphs_compiled(
        self, graphs: dict[UUID, ResourceGraph]
    ) -> None:
        """Called after dependency injection graphs are compiled."""
        _ = graphs
        return None

    async def on_test_start(self, test: ExecutableTest, run: ExecutedRun) -> None:
        """Called before a test starts executing."""
        _ = test, run
        return None

    async def on_execution_complete(
        self, execution: ExecutedTest, run: ExecutedRun
    ) -> None:
        """Called when any test node (leaf or composite) completes."""
        _ = execution, run
        return None

    async def on_run_stopped_early(self, failure_count: int, run: ExecutedRun) -> None:
        """Called when run stops early due to maxfail limit."""
        _ = failure_count, run
        return None

    async def on_run_complete(self, run: ExecutedRun) -> None:
        """Called after all tests complete."""
        _ = run
        return None

    def close(self) -> None:
        """Release processor resources."""
        return None
