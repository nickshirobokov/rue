"""OpenTelemetry-backed spans for Rue tests."""

from rue.telemetry.otel.trace import OtelTrace
from rue.telemetry.otel.runtime import otel_span


__all__ = [
    "OtelTrace",
    "otel_span",
]
