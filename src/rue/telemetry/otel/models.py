"""OpenTelemetry transport models."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict

from rue.telemetry.models import TelemetryArtifact


class OtelTraceArtifact(TelemetryArtifact):
    """Finished OpenTelemetry trace artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    spans: list[dict[str, Any]]
