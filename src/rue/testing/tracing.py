"""Per-execution telemetry orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

from rue.config import Config
from rue.telemetry.base import TelemetryArtifact
from rue.telemetry.backends.base import TelemetryBackend
from rue.telemetry.otel.backend import OtelTelemetryBackend
from rue.testing.models import LoadedTestDef, TestResult

T = TypeVar("T", bound=TelemetryBackend)


@dataclass(slots=True)
class TestTracer:
    """Coordinates telemetry backends for one concrete execution."""

    __test__ = False

    run_id: UUID
    backends: tuple[TelemetryBackend, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        config: Config,
        run_id: UUID,
    ) -> TestTracer:
        """Build a tracer by resolving telemetry backends from config flags."""
        backends: list[TelemetryBackend] = []
        if config.otel:
            backends.append(OtelTelemetryBackend())
        return cls(run_id=run_id, backends=tuple(backends))

    def start(self, definition: LoadedTestDef, execution_id: UUID) -> None:
        for backend in self.backends:
            backend.start(
                definition,
                run_id=self.run_id,
                execution_id=execution_id,
            )

    def record_result(self, result: TestResult) -> None:
        for backend in self.backends:
            backend.record_result(result)

    def finish(self) -> tuple[TelemetryArtifact, ...]:
        artifacts: list[TelemetryArtifact] = []
        for backend in self.backends:
            artifacts.extend(backend.finish())
        return tuple(artifacts)

    def get_backend(self, backend_type: type[T]) -> T | None:
        for backend in self.backends:
            if isinstance(backend, backend_type):
                return backend
        return None
