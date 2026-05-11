"""Suite event processor that records Rue suites into Turso."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import turso

from rue.events import SuiteEventsProcessor
from rue.storage.store import TursoSuiteStore
from rue.storage.views import StoredSuiteView, StoredTestExecutionView


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from rue.config import Config
    from rue.testing.execution.suite.models import ExecutedSuite
    from rue.testing.execution.test.base import ExecutableTest
    from rue.testing.execution.test.models import ExecutedTest


MAX_TRANSACTION_ATTEMPTS = 3


class TursoSuiteRecorder(SuiteEventsProcessor):
    """Persists suite lifecycle events into Turso."""

    def __init__(self) -> None:
        self.store = TursoSuiteStore()
        self._conn: turso.Connection | None = None
        self._parents_by_child: dict[UUID, UUID] = {}
        self._children_by_parent: dict[UUID, list[UUID]] = {}
        self._completed: set[UUID] = set()

    @property
    def path(self) -> Path:
        """Return the configured logical database path."""
        return self.store.path

    def configure(self, config: Config) -> None:
        """Apply runtime storage configuration."""
        self.store = TursoSuiteStore(config.database_path)

    def close(self) -> None:
        """Close the active Turso connection, if one is open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def on_suite_execution_start(self, suite: ExecutedSuite) -> None:
        """Initialize storage and persist the initial suite row."""
        self._parents_by_child = {}
        self._children_by_parent = {}
        self._completed = set()
        self.store.initialize()
        self._conn = self.store.connect()
        self._write(StoredSuiteView.from_suite(suite).insert)

    async def on_tests_ready(
        self,
        tests: list[ExecutableTest],
        suite: ExecutedSuite,
    ) -> None:
        """Record expected test execution tree relationships."""
        _ = suite
        for test in tests:
            self._record_tree(test)

    async def on_test_execution_complete(
        self,
        execution: ExecutedTest,
        suite: ExecutedSuite,
    ) -> None:
        """Persist one completed test execution and link finished children."""
        child_ids = [
            child.test_execution_id for child in execution.sub_test_executions
        ]
        if child_ids:
            self._children_by_parent[execution.test_execution_id] = child_ids
            for child_id in child_ids:
                self._parents_by_child[child_id] = execution.test_execution_id
        parent_id = self._parents_by_child.get(execution.test_execution_id)
        persisted_parent_id = (
            parent_id if parent_id in self._completed else None
        )
        view = StoredTestExecutionView.from_test_execution(
            suite.suite_execution_id,
            execution,
            persisted_parent_id,
            child_ids=tuple(
                self._children_by_parent.get(execution.test_execution_id, ())
            ),
        )
        self._write(view.insert)
        self._completed.add(execution.test_execution_id)

    async def on_suite_execution_complete(self, suite: ExecutedSuite) -> None:
        """Persist final suite counters and suite-level metrics."""
        self._write(StoredSuiteView.from_suite(suite).finish)

    def _connection(self) -> turso.Connection:
        if self._conn is None:
            self.store.initialize()
            self._conn = self.store.connect()
        return self._conn

    def _write(self, operation: Callable[[turso.Connection], None]) -> None:
        conn = self._connection()
        for attempt in range(MAX_TRANSACTION_ATTEMPTS):
            conn.execute("BEGIN CONCURRENT")
            try:
                operation(conn)
                conn.execute("COMMIT")
                return
            except turso.DatabaseError as error:
                conn.execute("ROLLBACK")
                if (
                    "conflict" in str(error).casefold()
                    and attempt + 1 < MAX_TRANSACTION_ATTEMPTS
                ):
                    continue
                raise

    def _record_tree(self, test: ExecutableTest) -> None:
        child_ids = [child.test_execution_id for child in test.children]
        if child_ids:
            self._children_by_parent[test.test_execution_id] = child_ids
            for child_id in child_ids:
                self._parents_by_child[child_id] = test.test_execution_id
        for child in test.children:
            self._record_tree(child)


__all__ = ["TursoSuiteRecorder"]
