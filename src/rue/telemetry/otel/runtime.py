"""Internal runner-managed OpenTelemetry runtime."""

from __future__ import annotations

import json
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from uuid import UUID

from opentelemetry import trace
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import INVALID_SPAN, Span

from rue.context import get_test_tracer


@dataclass(slots=True)
class OtelTraceSession:
    """OpenTelemetry session bound to a single test execution."""

    run_id: UUID
    execution_id: UUID
    root_span: Span
    otel_content: bool
    _spans: list[ReadableSpan] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def add_span(self, span: ReadableSpan) -> None:
        with self._lock:
            self._spans.append(span)

    def get_spans(self) -> list[ReadableSpan]:
        with self._lock:
            return list(self._spans)

    def serialize(self) -> dict[str, Any]:
        """Convert the finished trace session to a JSON-serializable payload."""
        with self._lock:
            return {
                "run_id": str(self.run_id),
                "execution_id": str(self.execution_id),
                "spans": [
                    json.loads(span.to_json(indent=None))
                    for span in self._spans
                ],
            }


class SessionAwareSpanExporter(SpanExporter):
    """Exports only spans that belong to active Rue OpenTelemetry sessions."""

    def __init__(self) -> None:
        self._write_lock = Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            session = otel_runtime.get_otel_trace(span.context.trace_id)
            if session is None:
                continue
            with self._write_lock:
                session.add_span(span)

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        _ = timeout_millis
        return True


class OtelRuntime:
    """Process-global OpenTelemetry runtime managed by Rue Runner."""

    def __init__(self) -> None:
        self._initialized = False
        self._exporter: SessionAwareSpanExporter | None = None
        self._init_lock = Lock()
        self._otel_traces: dict[int, OtelTraceSession] = {}
        self._otel_traces_lock = Lock()

    def configure(self, *, service_name: str = "rue") -> None:
        with self._init_lock:
            if not self._initialized:
                self._exporter = SessionAwareSpanExporter()
                provider = TracerProvider(
                    resource=Resource.create({"service.name": service_name})
                )
                provider.add_span_processor(SimpleSpanProcessor(self._exporter))
                trace.set_tracer_provider(provider)
                self._instrument_llm_clients()
                self._initialized = True

    def start_otel_trace(
        self,
        root_span: Span,
        *,
        run_id: UUID,
        execution_id: UUID,
        otel_content: bool,
    ) -> OtelTraceSession:
        session = OtelTraceSession(
            run_id=run_id,
            execution_id=execution_id,
            root_span=root_span,
            otel_content=otel_content,
        )
        with self._otel_traces_lock:
            self._otel_traces[root_span.get_span_context().trace_id] = session
        return session

    def finish_otel_trace(self, session: OtelTraceSession) -> OtelTraceSession:
        with self._otel_traces_lock:
            self._otel_traces.pop(
                session.root_span.get_span_context().trace_id, None
            )
        return session

    def get_otel_trace(self, trace_id: int) -> OtelTraceSession | None:
        with self._otel_traces_lock:
            return self._otel_traces.get(trace_id)

    @contextmanager
    def start_as_current_span(self, name: str):
        """Create a current OpenTelemetry span under Rue's tracer."""
        with trace.get_tracer("rue").start_as_current_span(name) as span:
            yield span

    @contextmanager
    def otel_span(self, name: str, attributes: dict[str, Any] | None = None):
        """Create a child span when inside an active OpenTelemetry-enabled test."""
        tracer = get_test_tracer()
        if tracer is None or tracer.otel_trace_session is None:
            yield INVALID_SPAN
            return

        with self.start_as_current_span(name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
            yield span

    @staticmethod
    def _instrument_llm_clients() -> None:
        OpenAIInstrumentor().instrument()
        AnthropicInstrumentor().instrument()


otel_runtime = OtelRuntime()
otel_span = otel_runtime.otel_span
