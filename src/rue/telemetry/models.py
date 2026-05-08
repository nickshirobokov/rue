"""Shared telemetry transport models."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TelemetryArtifact(BaseModel):
    """Stable transport model for finished telemetry output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    suite_execution_id: UUID
    test_execution_id: UUID
