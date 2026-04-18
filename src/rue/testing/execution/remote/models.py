"""Serializable remote execution payloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.resources.models import ResolverSnapshot
from rue.testing.models import TestResult
from rue.testing.models.spec import SetupFileRef, TestSpec


@dataclass(frozen=True, slots=True)
class ExecutorPayload:
    """Minimal, fully-serializable payload for remote test execution."""

    spec: TestSpec
    suite_root: Path
    setup_chain: tuple[SetupFileRef, ...]
    params: dict[str, Any]
    snapshot: ResolverSnapshot
    run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RemoteExecutionResult:
    result: TestResult
    worker_diff: dict[str, Any]
    ignored_paths: dict[str, list[str]]
