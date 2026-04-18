"""Base reporter ABC for rue test output."""

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID


if TYPE_CHECKING:
    from rue.config import Config
    from rue.testing import LoadedTestDef
    from rue.testing.execution.interfaces import ExecutableTest
    from rue.testing.models.executed import ExecutedTest
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
    def configure(self, config: Config) -> None:
        """Adjust reporter parameters based on runtime config."""

    @abstractmethod
    async def on_no_tests_found(self) -> None:
        """Called when test collection finds no tests."""

    @abstractmethod
    async def on_collection_complete(
        self, items: list[LoadedTestDef], run: Run
    ) -> None:
        """Called after test collection completes."""

    async def on_tests_ready(self, tests: list[ExecutableTest]) -> None:
        """Called after all executable test trees are built, before execution starts."""
        _ = tests
        return None

    async def on_test_start(self, item: LoadedTestDef) -> None:
        """Called before a test starts executing."""
        _ = item
        return None

    @abstractmethod
    async def on_execution_complete(self, execution: ExecutedTest) -> None:
        """Called when any test node (leaf or composite) completes."""

    @abstractmethod
    async def on_run_complete(self, run: Run) -> None:
        """Called after all tests complete."""

    @abstractmethod
    async def on_run_stopped_early(self, failure_count: int) -> None:
        """Called when run stops early due to maxfail limit."""

    async def on_trace_collected(
        self, tracer: TestTracer, execution_id: UUID
    ) -> None:
        """Called when a test finishes collecting trace data."""
        _ = tracer, execution_id
        return None
