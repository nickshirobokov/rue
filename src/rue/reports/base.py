"""Base reporter ABC for rue test output."""

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID


if TYPE_CHECKING:
    from rue.config import RueConfig
    from rue.testing import TestDefinition
    from rue.testing.models.result import TestExecution
    from rue.testing.models.run import Run
    from rue.testing.tracing import TestTracer


class ReporterMeta(ABCMeta):
    """Registers reporter instances after successful initialization."""

    def __call__(cls, *args, **kwargs):
        reporter = super().__call__(*args, **kwargs)
        Reporter.REGISTRY[cls.__name__] = reporter
        return reporter


class Reporter(ABC, metaclass=ReporterMeta):
    """Abstract base class for test reporters.

    All methods are async to support I/O-bound reporters (web dashboard, file output, etc.).
    """

    REGISTRY: ClassVar[dict[str, Reporter]] = {}

    @abstractmethod
    def configure(self, config: RueConfig) -> None:
        """Adjust reporter parameters based on runtime config."""

    @abstractmethod
    async def on_no_tests_found(self) -> None:
        """Called when test collection finds no tests."""

    @abstractmethod
    async def on_collection_complete(self, items: list[TestDefinition]) -> None:
        """Called after test collection completes."""

    async def on_test_start(self, item: TestDefinition) -> None:
        """Called before a test starts executing."""
        _ = item
        return None

    async def on_subtest_complete(
        self,
        parent: TestDefinition,
        sub_execution: TestExecution,
    ) -> None:
        """Called when a subtest execution completes."""
        _ = parent, sub_execution
        return None

    @abstractmethod
    async def on_test_complete(self, execution: TestExecution) -> None:
        """Called after each test completes."""

    @abstractmethod
    async def on_run_complete(self, run: Run) -> None:
        """Called after all tests complete."""

    @abstractmethod
    async def on_run_stopped_early(self, failure_count: int) -> None:
        """Called when run stops early due to maxfail limit."""

    async def on_trace_collected(
        self, tracer: TestTracer, execution_id: UUID
    ) -> None:
        """Called when a test tracer finishes collecting trace data."""
        _ = tracer, execution_id
        return None
