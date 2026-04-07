"""Internal runner-managed OpenTelemetry runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from threading import Lock
from uuid import UUID

from opentelemetry import trace
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import (
    ReadableSpan,
    Span,
    SpanProcessor,
    TracerProvider,
)
from rue.context.runtime import CURRENT_SUT_SPAN_IDS


@dataclass(slots=True)
class OtelTraceSession:
    """OpenTelemetry session bound to a single test execution."""

    run_id: UUID
    execution_id: UUID
    root_span: Span
    otel_content: bool
    _spans: list[ReadableSpan] = field(default_factory=list)
    _sut_owners: dict[int, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def add_span(self, span: ReadableSpan) -> None:
        with self._lock:
            self._spans.append(span)

    def record_sut_owner(self, span_id: int, owner_span_id: int) -> None:
        with self._lock:
            self._sut_owners[span_id] = owner_span_id

    def get_spans(self) -> list[ReadableSpan]:
        with self._lock:
            return list(self._spans)

    def get_sut_owner(self, span_id: int) -> int | None:
        with self._lock:
            return self._sut_owners.get(span_id)

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


class SessionAwareSpanProcessor(SpanProcessor):
    """Routes spans into active Rue sessions and records SUT ownership."""

    def __init__(self) -> None:
        self._write_lock = Lock()

    def on_start(
        self,
        span: Span,
        parent_context: trace.Context | None = None,
    ) -> None:
        _ = parent_context
        session = otel_runtime.get_otel_trace(span.get_span_context().trace_id)
        if session is None:
            return

        owner_span_ids = CURRENT_SUT_SPAN_IDS.get()
        if not owner_span_ids:
            return

        with self._write_lock:
            session.record_sut_owner(
                span.get_span_context().span_id,
                owner_span_ids[-1],
            )

    def on_end(self, span: ReadableSpan) -> None:
        session = otel_runtime.get_otel_trace(span.context.trace_id)
        if session is None:
            return
        with self._write_lock:
            session.add_span(span)

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        _ = timeout_millis
        return True


class OtelRuntime:
    """Process-global OpenTelemetry runtime managed by Rue Runner."""

    def __init__(self) -> None:
        self._initialized = False
        self._processor: SessionAwareSpanProcessor | None = None
        self._init_lock = Lock()
        self._otel_traces: dict[int, OtelTraceSession] = {}
        self._otel_traces_lock = Lock()

    def configure(self, *, service_name: str = "rue") -> None:
        with self._init_lock:
            if not self._initialized:
                self._processor = SessionAwareSpanProcessor()
                provider = TracerProvider(
                    resource=Resource.create({"service.name": service_name})
                )
                provider.add_span_processor(self._processor)
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

    def start_as_current_span(self, name: str):
        """Create a current OpenTelemetry span under Rue's tracer."""
        return trace.get_tracer("rue").start_as_current_span(name)

    @staticmethod
    def _instrument_llm_clients() -> None:
        OpenAIInstrumentor().instrument()
        AnthropicInstrumentor().instrument()


otel_runtime = OtelRuntime()
