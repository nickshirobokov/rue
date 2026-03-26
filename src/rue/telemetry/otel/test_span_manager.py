"""OpenTelemetry span manager for Rue test execution."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opentelemetry.trace import Span, StatusCode

from rue.telemetry.otel.runtime import otel_runtime


if TYPE_CHECKING:
    from rue.testing.models import TestDefinition, TestResult


@dataclass
class OtelTestSpanManager:
    """Creates and records OpenTelemetry root spans for test execution."""

    enabled: bool = False
    otel_content: bool = True

    @contextmanager
    def span(self, definition: TestDefinition) -> Iterator[Span | None]:
        """Context manager for an optional test root span."""
        if not self.enabled or not otel_runtime.is_configured():
            yield None
            return

        with otel_runtime.start_as_current_span(f"test.{definition.full_name}") as span:
            span.set_attribute("test.name", definition.name)
            span.set_attribute("test.module", str(definition.module_path))
            if definition.tags:
                span.set_attribute("test.tags", list(definition.tags))
            if definition.suffix:
                span.set_attribute("test.id_suffix", definition.suffix)
            if definition.case_id:
                span.set_attribute("test.case_id", str(definition.case_id))
            yield span

    def get_otel_trace_id(self, span: Span | None) -> str | None:
        """Extract the OpenTelemetry trace ID from a span."""
        if not span:
            return None
        ctx = span.get_span_context()
        return format(ctx.trace_id, "032x") if ctx.trace_id else None

    def record(self, span: Span | None, result: TestResult) -> None:
        """Record test result attributes on the root span."""
        if not span:
            return
        span.set_attribute("test.status", result.status.value)
        span.set_attribute("test.duration_ms", result.duration_ms)
        if result.error:
            span.set_status(StatusCode.ERROR, str(result.error))
            span.record_exception(result.error)
