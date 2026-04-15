"""Per-execution tracing state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from opentelemetry.trace import Span, StatusCode

from rue.telemetry.otel.runtime import OtelTraceSession, otel_runtime
from rue.testing.models import LoadedTestDef, TestResult


@dataclass(slots=True)
class TestTracer:
    """Stores tracing state for a single test execution."""

    __test__ = False

    otel_enabled: bool
    run_id: UUID | None = None
    otel_root_span: Span | None = None
    otel_trace_session: OtelTraceSession | None = None
    completed_otel_trace_session: OtelTraceSession | None = None
    _otel_root_span_scope: Any = field(default=None, init=False, repr=False)

    @property
    def has_otel_trace(self) -> bool:
        return self.otel_trace_session is not None

    @property
    def otel_trace_id(self) -> str | None:
        span = self.completed_otel_trace_session
        if span is not None:
            return format(span.root_span.get_span_context().trace_id, "032x")
        if self.otel_root_span is None:
            return None
        return format(self.otel_root_span.get_span_context().trace_id, "032x")

    def start_otel_root_span(self, definition: LoadedTestDef) -> Span | None:
        if not self.otel_enabled:
            return None

        scope = otel_runtime.start_as_current_span(
            f"test.{definition.spec.full_name}"
        )
        span = scope.__enter__()
        self._otel_root_span_scope = scope
        self.otel_root_span = span
        span.set_attribute("test.name", definition.spec.name)
        span.set_attribute("test.module", str(definition.spec.module_path))
        if definition.spec.tags:
            span.set_attribute("test.tags", list(definition.spec.tags))
        if definition.spec.suffix:
            span.set_attribute("test.suffix", definition.spec.suffix)
        if definition.spec.case_id:
            span.set_attribute("test.case_id", str(definition.spec.case_id))
        return span

    def start_otel_trace(
        self, *, execution_id: UUID
    ) -> OtelTraceSession | None:
        if self.otel_root_span is None or self.run_id is None:
            return None

        self.otel_trace_session = otel_runtime.start_otel_trace(
            self.otel_root_span,
            run_id=self.run_id,
            execution_id=execution_id,
        )
        return self.otel_trace_session

    def record_otel_result(self, result: TestResult) -> None:
        if self.otel_root_span is None:
            return

        self.otel_root_span.set_attribute("test.status", result.status.value)
        self.otel_root_span.set_attribute(
            "test.duration_ms", result.duration_ms
        )
        if result.error:
            self.otel_root_span.set_status(StatusCode.ERROR, str(result.error))
            self.otel_root_span.record_exception(result.error)

    def finish_otel_trace(self) -> OtelTraceSession | None:
        if self._otel_root_span_scope is not None:
            self._otel_root_span_scope.__exit__(None, None, None)
            self._otel_root_span_scope = None

        if self.otel_trace_session is not None:
            self.completed_otel_trace_session = otel_runtime.finish_otel_trace(
                self.otel_trace_session
            )
            self.otel_trace_session = None

        return self.completed_otel_trace_session
