"""Abstract base class for storage backends."""

from abc import ABC, abstractmethod
from uuid import UUID

from rue.testing.models.run import Run


class Store(ABC):
    """Abstract storage backend for Rue test runs."""

    @abstractmethod
    def save_run(self, run: Run) -> None:
        """Save a complete test run."""

    @abstractmethod
    def get_run(self, run_id: UUID) -> Run | None:
        """Retrieve a test run by ID."""

    @abstractmethod
    def list_runs(self, limit: int = 10) -> list[Run]:
        """List recent runs, ordered by start_time descending."""
