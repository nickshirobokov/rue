"""Session-scoped state shared across renderers during a test run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rue.testing import TestDefinition
    from rue.testing.execution.interfaces import Test
    from rue.testing.models.result import TestExecution


@dataclass
class SessionState:
    items: list[TestDefinition] = field(default_factory=list)
    item_ids: set[int] = field(default_factory=set)
    items_by_file: dict[Path, list[TestDefinition]] = field(default_factory=dict)
    total_tests: int = 0
    completed_count: int = 0
    tests: dict[int, Test] = field(default_factory=dict)
    executions: dict[int, TestExecution] = field(default_factory=dict)
    failures: list[TestExecution] = field(default_factory=list)
    current_module: Path | None = None

    def reset(
        self,
        items: list[TestDefinition],
    ) -> None:
        self.items = list(items)
        self.item_ids = {id(item) for item in items}
        self.items_by_file = {}
        for item in items:
            self.items_by_file.setdefault(item.module_path, []).append(item)
        self.total_tests = len(items)
        self.completed_count = 0
        self.tests = {}
        self.executions = {}
        self.failures = []
        self.current_module = None
