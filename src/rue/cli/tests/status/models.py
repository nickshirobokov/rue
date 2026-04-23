"""Models used by `rue tests status`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from rue.resources import ResourceSpec
from rue.testing.models import LoadedTestDef, Run, TestStatus


@dataclass(frozen=True)
class StatusIssue:
    phase: Literal["load", "definition", "resolve"]
    message: str
    node_key: str | None = None


@dataclass(frozen=True)
class StatusNode:
    definition: LoadedTestDef
    backend: str | None
    history: tuple[TestStatus | None, ...] = ()
    issues: tuple[StatusIssue, ...] = ()
    resources: tuple[ResourceSpec, ...] = ()
    metrics: tuple[ResourceSpec, ...] = ()
    children: tuple["StatusNode", ...] = ()
    leaf_count: int = 1


@dataclass(frozen=True)
class TestsStatusReport:
    run_window: tuple[Run, ...] = ()
    module_nodes: dict[Path, list[StatusNode]] = field(default_factory=dict)


@dataclass(frozen=True)
class _DraftNode:
    definition: LoadedTestDef
    backend: str
    params: dict[str, Any]
    node_key: str
    children: tuple["_DraftNode", ...] = ()


__all__ = ["StatusIssue", "StatusNode", "TestsStatusReport", "_DraftNode"]
