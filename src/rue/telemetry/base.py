"""Shared telemetry transport models."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TelemetryArtifact(BaseModel):
    """Stable transport model for finished telemetry output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    execution_id: UUID
