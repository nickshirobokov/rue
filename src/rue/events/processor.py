"""Base processor ABC for run lifecycle events."""

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID


if TYPE_CHECKING:
    from rue.config import Config
    from rue.resources.models import ResourceGraph
    from rue.testing import LoadedTestDef
    from rue.testing.execution.base import ExecutableTest
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import Run


class RunEventsProcessorMeta(ABCMeta):
    """Registers processor instances after successful initialization."""

    def __call__(
        cls, *args: Any, **kwargs: Any
    ) -> RunEventsProcessor:
        """Create and register a run event processor."""
        processor = super().__call__(*args, **kwargs)
        RunEventsProcessor.REGISTRY[cls.__name__] = processor
        return processor


class RunEventsProcessor(ABC, metaclass=RunEventsProcessorMeta):
    """Abstract base class for run lifecycle event processors."""

    REGISTRY: ClassVar[dict[str, RunEventsProcessor]] = {}

    @abstractmethod
    def configure(self, config: Config) -> None:
        """Adjust processor parameters based on runtime config."""

    async def on_run_start(self, run: Run) -> None:
        """Called when a run starts."""
        _ = run
        return None

    @abstractmethod
    async def on_no_tests_found(self, run: Run) -> None:
        """Called when test collection finds no tests."""

    @abstractmethod
    async def on_collection_complete(
        self, items: list[LoadedTestDef], run: Run
    ) -> None:
        """Called after test collection completes."""

    async def on_tests_ready(
        self, tests: list[ExecutableTest], run: Run
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

    async def on_test_start(self, test: ExecutableTest, run: Run) -> None:
        """Called before a test starts executing."""
        _ = test, run
        return None

    @abstractmethod
    async def on_execution_complete(
        self, execution: ExecutedTest, run: Run
    ) -> None:
        """Called when any test node (leaf or composite) completes."""

    @abstractmethod
    async def on_run_stopped_early(
        self, failure_count: int, run: Run
    ) -> None:
        """Called when run stops early due to maxfail limit."""

    @abstractmethod
    async def on_run_complete(self, run: Run) -> None:
        """Called after all tests complete."""
