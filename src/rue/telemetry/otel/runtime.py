"""Internal runner-managed OpenTelemetry runtime."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from opentelemetry import trace
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import INVALID_SPAN, Span

from rue.context import get_otel_trace_session


@dataclass(slots=True)
class OtelTraceSnapshot:
    """Finished OpenTelemetry data for a single test execution."""

    otel_trace_id: str
    spans: tuple[ReadableSpan, ...]


@dataclass(slots=True)
class OtelTraceSession:
    """Active OpenTelemetry session bound to a single test execution."""

    otel_trace_id: str
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

    def snapshot(self) -> OtelTraceSnapshot:
        with self._lock:
            return OtelTraceSnapshot(
                otel_trace_id=self.otel_trace_id,
                spans=tuple(self._spans),
            )


class SessionAwareSpanExporter(SpanExporter):
    """Exports only spans that belong to active Rue OpenTelemetry sessions."""

    def __init__(self, output_path: Path | str) -> None:
        self._write_lock = Lock()
        self.output_path = Path(output_path)
        self._prepare_output()

    def configure_output(self, output_path: Path | str) -> None:
        self.output_path = Path(output_path)
        self._prepare_output()

    def _prepare_output(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("")

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        serialized: list[str] = []

        for span in spans:
            otel_trace_id = format(span.context.trace_id, "032x")
            session = otel_runtime.get_otel_trace(otel_trace_id)
            if session is None:
                continue
            session.add_span(span)
            serialized.append(span.to_json(indent=None))

        if not serialized:
            return SpanExportResult.SUCCESS

        with self._write_lock:
            with self.output_path.open("a", encoding="utf-8") as handle:
                for line in serialized:
                    handle.write(line + "\n")

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
        self._otel_traces: dict[str, OtelTraceSession] = {}
        self._otel_traces_lock = Lock()

    def configure(self, output_path: Path | str, *, service_name: str = "rue") -> None:
        with self._init_lock:
            if not self._initialized:
                self._exporter = SessionAwareSpanExporter(output_path)
                provider = TracerProvider(
                    resource=Resource.create({"service.name": service_name})
                )
                provider.add_span_processor(SimpleSpanProcessor(self._exporter))
                trace.set_tracer_provider(provider)
                self._instrument_llm_clients()
                self._initialized = True
                return

            if self._exporter is None:
                msg = "OpenTelemetry runtime exporter is missing."
                raise RuntimeError(msg)
            self._exporter.configure_output(output_path)

    def is_configured(self) -> bool:
        return self._initialized and self._exporter is not None

    def start_otel_trace(self, root_span: Span, *, otel_content: bool) -> OtelTraceSession:
        otel_trace_id = format(root_span.get_span_context().trace_id, "032x")
        session = OtelTraceSession(
            otel_trace_id=otel_trace_id,
            root_span=root_span,
            otel_content=otel_content,
        )
        with self._otel_traces_lock:
            self._otel_traces[otel_trace_id] = session
        return session

    def finish_otel_trace(self, session: OtelTraceSession) -> OtelTraceSnapshot:
        with self._otel_traces_lock:
            self._otel_traces.pop(session.otel_trace_id, None)
        return session.snapshot()

    def get_otel_trace(self, otel_trace_id: str) -> OtelTraceSession | None:
        with self._otel_traces_lock:
            return self._otel_traces.get(otel_trace_id)

    def get_current_otel_trace(self) -> OtelTraceSession | None:
        """Return the current active OpenTelemetry session, if any."""
        return get_otel_trace_session()

    def is_otel_trace_active(self) -> bool:
        """Whether code is running inside an OpenTelemetry-enabled SingleTest."""
        return self.get_current_otel_trace() is not None

    def is_otel_content_enabled(self) -> bool:
        """Whether content-bearing span attributes should be attached."""
        session = self.get_current_otel_trace()
        return session.otel_content if session is not None else False

    @contextmanager
    def start_as_current_span(self, name: str):
        """Create a current OpenTelemetry span under Rue's tracer."""
        with trace.get_tracer("rue").start_as_current_span(name) as span:
            yield span

    @contextmanager
    def otel_span(self, name: str, attributes: dict[str, Any] | None = None):
        """Create a child span when inside an OpenTelemetry-enabled SingleTest."""
        if not self.is_otel_trace_active():
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
