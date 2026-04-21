"""OpenTelemetry-backed telemetry backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from typing import Any
from uuid import UUID

from opentelemetry.trace import Span, StatusCode

from rue.telemetry.base import TelemetryArtifact
from rue.telemetry.backends.base import TelemetryBackend
from rue.telemetry.otel.runtime import OtelTraceSession, otel_runtime
from pydantic import ConfigDict

if TYPE_CHECKING:
    from rue.testing.models import LoadedTestDef, TestResult


class OtelTraceArtifact(TelemetryArtifact):
    """Finished OpenTelemetry trace artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    spans: list[dict[str, Any]]


@dataclass(slots=True)
class OtelTelemetryBackend(TelemetryBackend):
    """Collects one finished OpenTelemetry trace artifact per execution."""

    _root_span: Span | None = None
    _session: OtelTraceSession | None = None
    _completed_session: OtelTraceSession | None = None
    _root_span_scope: Any = field(default=None, init=False, repr=False)

    @property
    def active_session(self) -> OtelTraceSession | None:
        return self._session

    def start(
        self,
        definition: LoadedTestDef,
        *,
        run_id: UUID,
        execution_id: UUID,
    ) -> None:
        otel_runtime.configure()
        scope = otel_runtime.start_as_current_span(
            f"test.{definition.spec.full_name}"
        )
        span = scope.__enter__()
        self._root_span_scope = scope
        self._root_span = span
        span.set_attribute("test.name", definition.spec.name)
        span.set_attribute("test.module", str(definition.spec.module_path))
        if definition.spec.tags:
            span.set_attribute("test.tags", list(definition.spec.tags))
        if definition.spec.suffix:
            span.set_attribute("test.suffix", definition.spec.suffix)
        if definition.spec.case_id:
            span.set_attribute("test.case_id", str(definition.spec.case_id))
        self._session = otel_runtime.start_otel_trace(
            span,
            run_id=run_id,
            execution_id=execution_id,
        )

    def record_result(self, result: TestResult) -> None:
        if self._root_span is None:
            return

        self._root_span.set_attribute("test.status", result.status.value)
        self._root_span.set_attribute("test.duration_ms", result.duration_ms)
        if result.error:
            self._root_span.set_status(StatusCode.ERROR, str(result.error))
            self._root_span.record_exception(result.error)

    def finish(self) -> tuple[TelemetryArtifact, ...]:
        if self._root_span_scope is not None:
            self._root_span_scope.__exit__(None, None, None)
            self._root_span_scope = None

        if self._session is None:
            self._root_span = None
            return ()

        self._completed_session = otel_runtime.finish_otel_trace(self._session)
        self._session = None
        self._root_span = None
        payload = self._completed_session.serialize()
        return (
            OtelTraceArtifact(
                run_id=self._completed_session.run_id,
                execution_id=self._completed_session.execution_id,
                trace_id=format(
                    self._completed_session.root_span.get_span_context().trace_id,
                    "032x",
                ),
                spans=payload["spans"],
            ),
        )
