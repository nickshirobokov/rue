"""Models used by `rue tests status`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rue.resources import ResourceSpec
from rue.testing.execution.backend import ExecutionBackend
from rue.testing.models import ExecutedRun, LoadedTestDef, TestStatus


@dataclass(frozen=True)
class StatusIssue:
    """Static status issue for a collected test node."""

    phase: Literal["resolve"]
    message: str


@dataclass(frozen=True)
class StatusNode:
    """Rendered status tree node."""

    definition: LoadedTestDef
    backend: ExecutionBackend | None
    history: tuple[TestStatus | None, ...] = ()
    issues: tuple[StatusIssue, ...] = ()
    resources_by_type: dict[str, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    children: tuple[StatusNode, ...] = ()
    leaf_count: int = 1


@dataclass(frozen=True)
class TestsStatusReport:
    """Status command report model."""

    run_window: tuple[ExecutedRun, ...] = ()
    module_nodes: dict[Path, list[StatusNode]] = field(default_factory=dict)


__all__ = ["StatusIssue", "StatusNode", "TestsStatusReport"]
