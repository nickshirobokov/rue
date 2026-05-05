"""Telemetry backend interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

from rue.telemetry.models import TelemetryArtifact


if TYPE_CHECKING:
    from rue.testing.models import LoadedTestDef, TestResult


class TelemetryBackend(ABC):
    """Runtime collector that produces finished telemetry artifacts."""

    @abstractmethod
    def start(
        self,
        definition: LoadedTestDef,
        *,
        run_id: UUID,
        execution_id: UUID,
    ) -> None:
        """Start collecting telemetry for one concrete execution."""

    @abstractmethod
    def record_result(self, result: TestResult) -> None:
        """Record the final test result onto the active telemetry state."""

    @abstractmethod
    def finish(self) -> tuple[TelemetryArtifact, ...]:
        """Finish collection and return immutable transport artifacts."""
