"""Serializable remote execution payloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.config import Config
from rue.resources.models import ResolverSyncSnapshot
from rue.telemetry.base import TelemetryArtifact
from rue.testing.models import TestResult
from rue.testing.models.spec import SetupFileRef, TestSpec


@dataclass(frozen=True, slots=True)
class ExecutorPayload:
    """Minimal, fully-serializable payload for remote test execution."""

    spec: TestSpec
    suite_root: Path
    setup_chain: tuple[SetupFileRef, ...]
    params: dict[str, Any]
    snapshot: ResolverSyncSnapshot
    config: Config
    run_id: UUID
    execution_id: UUID


@dataclass(frozen=True, slots=True)
class RemoteExecutionResult:
    """Serializable remote execution outcome."""

    result: TestResult
    telemetry_artifacts: tuple[TelemetryArtifact, ...]
    sync_update: bytes
