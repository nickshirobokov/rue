"""Mutable state consumed by CLI renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from rue.testing.execution.test.models import TestStatus


if TYPE_CHECKING:
    from rue.testing.execution.test.base import ExecutableTest
    from rue.testing.execution.test.models import ExecutedTest, LoadedTestDef


@dataclass
class TerminalSuiteState:
    """Suite progress state consumed by terminal renderers."""

    verbosity: int = 0
    items: list[LoadedTestDef] = field(default_factory=list)
    item_keys: set[int] = field(default_factory=set)
    items_by_file: dict[Path, list[LoadedTestDef]] = field(default_factory=dict)
    total_tests: int = 0
    completed_count: int = 0
    tests: dict[int, ExecutableTest] = field(default_factory=dict)
    test_executions: dict[int, ExecutedTest] = field(default_factory=dict)
    all_test_executions: dict[int, ExecutedTest] = field(default_factory=dict)
    failures: list[ExecutedTest] = field(default_factory=list)
    status_counts: dict[TestStatus, int] = field(default_factory=dict)
    current_module: Path | None = None
    completed_modules: set[Path] = field(default_factory=set)

    def configure(self, verbosity: int) -> None:
        """Apply output verbosity to rendering state."""
        self.verbosity = verbosity

    def reset_collection(self, items: list[LoadedTestDef]) -> None:
        """Reset state for a newly collected suite."""
        self.items = list(items)
        self.item_keys = {item.spec.collection_index for item in items}
        self.items_by_file = {}
        for item in items:
            self.items_by_file.setdefault(
                item.spec.locator.module_path, []
            ).append(item)
        self.total_tests = len(items)
        self.completed_count = 0
        self.tests = {}
        self.test_executions = {}
        self.all_test_executions = {}
        self.failures = []
        self.status_counts = {}
        self.current_module = None
        self.completed_modules = set()

    def is_top_level_definition(self, item: LoadedTestDef) -> bool:
        """Return whether the definition is a collected top-level item."""
        return (
            item.spec.collection_index in self.item_keys
            and item.spec.suffix is None
            and item.spec.case_id is None
        )

    def record_ready_tests(self, tests: list[ExecutableTest]) -> None:
        """Cache top-level executable tests for live rendering."""
        for test in tests:
            if self.is_top_level_definition(test.definition):
                self.tests[test.definition.spec.collection_index] = test

    def record_test_execution(self, execution: ExecutedTest) -> bool:
        """Record a completed test execution and return if it is top-level."""
        self.all_test_executions[id(execution.definition)] = execution

        if not self.is_top_level_definition(execution.definition):
            return False

        self.test_executions[
            execution.definition.spec.collection_index
        ] = execution
        self.completed_count += 1
        status = execution.result.status
        self.status_counts[status] = self.status_counts.get(status, 0) + 1
        if status.is_failure:
            self.failures.append(execution)
        return True

    def is_module_complete(self, path: Path) -> bool:
        """Return whether every top-level item in a module has completed."""
        return all(
            item.spec.collection_index in self.test_executions
            for item in self.items_by_file.get(path, [])
        )

    def mark_module_completed(self, path: Path) -> None:
        """Mark a module as already printed in live terminal output."""
        self.completed_modules.add(path)

    @property
    def all_modules_complete(self) -> bool:
        """Return whether every collected module has completed."""
        return bool(self.items_by_file) and len(self.completed_modules) == len(
            self.items_by_file
        )


__all__ = ["TerminalSuiteState"]
