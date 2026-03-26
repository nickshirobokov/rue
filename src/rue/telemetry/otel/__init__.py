"""OpenTelemetry-backed spans for Rue tests."""

from rue.telemetry.otel.runtime import OtelTraceSession, otel_span
from rue.telemetry.otel.trace import OtelTrace


__all__ = [
    "OtelTrace",
    "OtelTraceSession",
    "otel_span",
]
