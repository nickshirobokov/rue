"""OpenTelemetry trace access for a running Rue test."""

from dataclasses import dataclass
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan

from rue.telemetry.otel.runtime import OtelTraceSession


@dataclass
class OtelTrace:
    """Provides access to OpenTelemetry data for the current test.

    Injected via dependency injection when a test declares `otel_trace`
    as a parameter. Allows querying child spans, LLM calls, and setting
    custom attributes on the test root span.
    """

    _session: OtelTraceSession

    @classmethod
    def from_session(cls, session: OtelTraceSession) -> "OtelTrace":
        """Create an OpenTelemetry trace view for the active test session."""
        return cls(_session=session)

    @property
    def otel_trace_id(self) -> str:
        """The OpenTelemetry trace ID for this test's span tree."""
        return self._session.otel_trace_id

    @property
    def otel_span_id(self) -> str:
        """The OpenTelemetry span ID for this test's root span."""
        return format(self._session.root_span.get_span_context().span_id, "016x")

    @property
    def is_enabled(self) -> bool:
        """Whether OpenTelemetry capture is enabled."""
        return True

    def get_child_spans(self) -> list[ReadableSpan]:
        """Get all spans created during this test's execution."""
        return self._session.get_spans()

    def get_llm_calls(self) -> list[ReadableSpan]:
        """Get spans from instrumented LLM API calls."""
        return [
            span
            for span in self.get_child_spans()
            if span.name.startswith(("openai.", "anthropic.", "gen_ai."))
        ]

    def get_sut_spans(self, name: str | None = None) -> list[ReadableSpan]:
        """Get spans from @rue.sut decorated functions."""
        spans = [
            span
            for span in self.get_child_spans()
            if span.attributes and span.attributes.get("rue.sut")
        ]
        if name:
            spans = [
                span for span in spans if span.attributes.get("rue.sut.name") == name
            ]
        return spans

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a custom attribute on the test root span."""
        self._session.root_span.set_attribute(key, value)
