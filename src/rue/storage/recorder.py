"""Run event processor that records Rue runs into Turso."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import turso

from rue.events import RunEventsProcessor
from rue.storage.store import TursoRunStore
from rue.storage.views import StoredExecutionView, StoredRunView


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from rue.config import Config
    from rue.testing.execution.executable import ExecutableTest
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import ExecutedRun


MAX_TRANSACTION_ATTEMPTS = 3


class TursoRunRecorder(RunEventsProcessor):
    """Persists run lifecycle events into Turso."""

    def __init__(self) -> None:
        self.store = TursoRunStore()
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
        self.store = TursoRunStore(config.database_path)

    def close(self) -> None:
        """Close the active Turso connection, if one is open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def on_run_start(self, run: ExecutedRun) -> None:
        """Initialize storage and persist the initial run row."""
        self._parents_by_child = {}
        self._children_by_parent = {}
        self._completed = set()
        self.store.initialize()
        self._conn = self.store.connect()
        self._write(StoredRunView.from_run(run).insert)

    async def on_tests_ready(
        self,
        tests: list[ExecutableTest],
        run: ExecutedRun,
    ) -> None:
        """Record expected execution tree relationships."""
        _ = run
        for test in tests:
            self._record_tree(test)

    async def on_execution_complete(
        self,
        execution: ExecutedTest,
        run: ExecutedRun,
    ) -> None:
        """Persist one completed execution and link finished children."""
        child_ids = [child.execution_id for child in execution.sub_executions]
        if child_ids:
            self._children_by_parent[execution.execution_id] = child_ids
            for child_id in child_ids:
                self._parents_by_child[child_id] = execution.execution_id
        parent_id = self._parents_by_child.get(execution.execution_id)
        persisted_parent_id = (
            parent_id if parent_id in self._completed else None
        )
        view = StoredExecutionView.from_execution(
            run.run_id,
            execution,
            persisted_parent_id,
            child_ids=tuple(
                self._children_by_parent.get(execution.execution_id, ())
            ),
        )
        self._write(view.insert)
        self._completed.add(execution.execution_id)

    async def on_run_complete(self, run: ExecutedRun) -> None:
        """Persist final run counters and run-level metrics."""
        self._write(StoredRunView.from_run(run).finish)

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
        child_ids = [child.execution_id for child in test.children]
        if child_ids:
            self._children_by_parent[test.execution_id] = child_ids
            for child_id in child_ids:
                self._parents_by_child[child_id] = test.execution_id
        for child in test.children:
            self._record_tree(child)


__all__ = ["TursoRunRecorder"]
