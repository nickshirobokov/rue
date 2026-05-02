"""Run event processor that streams run data into the database."""

from __future__ import annotations

import json
import linecache
import sqlite3
from dataclasses import asdict
from typing import TYPE_CHECKING, cast
from uuid import UUID

from rue.assertions.base import AssertionResult
from rue.events import RunEventsProcessor
from rue.predicates.models import PredicateResult
from rue.resources import ResourceSpec, Scope
from rue.storage.manager import MAX_STORED_RUNS
from rue.testing.models.spec import TestSpec


if TYPE_CHECKING:
    from rue.config import Config
    from rue.testing.execution.base import ExecutableTest
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import Run


MAX_REPR_LENGTH = 2000

RUN_INSERT_SQL = """
    INSERT INTO runs (
        run_id, start_time, end_time, total_duration_ms,
        passed, failed, errors, skipped, xfailed, xpassed,
        total, stopped_early, environment_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

RUN_UPDATE_SQL = """
    UPDATE runs SET
        end_time = ?,
        total_duration_ms = ?,
        passed = ?,
        failed = ?,
        errors = ?,
        skipped = ?,
        xfailed = ?,
        xpassed = ?,
        total = ?,
        stopped_early = ?,
        environment_json = ?
    WHERE run_id = ?
"""

EXECUTION_INSERT_SQL = """
    INSERT INTO test_executions (
        execution_id, run_id, parent_id, test_name, file_path, class_name,
        case_id, suffix, tags_json, skip_reason, xfail_reason,
        status, duration_ms, error_message, error_traceback
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

METRIC_INSERT_SQL = """
    INSERT INTO metrics (
        run_id, name, scope, value, value_json,
        first_recorded_at, last_recorded_at, consumers_json,
        provider_name, provider_scope, provider_path,
        provider_dir, depends_on_metrics_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

ASSERTION_INSERT_SQL = """
    INSERT INTO assertions (
        run_id, test_execution_id, metric_id, expression_repr, passed,
        error_message
    ) VALUES (?, ?, ?, ?, ?, ?)
"""

PREDICATE_INSERT_SQL = """
    INSERT INTO predicates (
        run_id, assertion_id, predicate_name, actual, reference,
        strict, confidence, value, message
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _scope_to_storage_value(scope: Scope | str) -> str:
    return scope.value if isinstance(scope, Scope) else str(scope)


class DBWriter(RunEventsProcessor):
    """Persists run lifecycle events directly to SQLite."""

    def __init__(self) -> None:
        self._parents_by_child: dict[UUID, UUID] = {}
        self._children_by_parent: dict[UUID, list[UUID]] = {}
        self._completed: set[UUID] = set()

    def configure(self, config: Config) -> None:
        """Use the configured database path."""
        self.path = config.db_path

    async def on_run_start(self, run: Run) -> None:
        """Persist the run shell before execution starts."""
        self._parents_by_child = {}
        self._children_by_parent = {}
        self._completed = set()
        self.start_run(run)

    async def on_tests_ready(
        self,
        tests: list[ExecutableTest],
        run: Run,
    ) -> None:
        """Record execution tree relationships before execution starts."""
        _ = run
        for test in tests:
            self._record_tree(test)

    async def on_execution_complete(
        self,
        execution: ExecutedTest,
        run: Run,
    ) -> None:
        """Persist one completed execution as soon as it is available."""
        child_ids = [child.execution_id for child in execution.sub_executions]
        if child_ids:
            self._children_by_parent[execution.execution_id] = child_ids
            for child_id in child_ids:
                self._parents_by_child[child_id] = execution.execution_id
        parent_id = self._parents_by_child.get(execution.execution_id)
        persisted_parent_id = (
            parent_id if parent_id in self._completed else None
        )
        self.record_execution(
            run.run_id,
            execution,
            parent_id=persisted_parent_id,
        )
        self._completed.add(execution.execution_id)
        linked_children = [
            child_id
            for child_id in self._children_by_parent.get(
                execution.execution_id,
                [],
            )
            if child_id in self._completed
        ]
        self.link_executions(execution.execution_id, linked_children)

    async def on_run_complete(self, run: Run) -> None:
        """Persist final run summary data."""
        self.finish_run(run)

    def start_run(self, run: Run) -> None:
        """Persist the initial run shell before executions start."""
        with self._connect() as conn:
            conn.execute(
                RUN_INSERT_SQL,
                (
                    str(run.run_id),
                    run.start_time.isoformat(),
                    None,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    json.dumps(run.environment.model_dump()),
                ),
            )

    def record_execution(
        self,
        run_id: UUID,
        execution: ExecutedTest,
        parent_id: UUID | None = None,
    ) -> None:
        """Persist one completed execution and its assertion data."""
        spec = execution.definition.spec
        error = execution.result.error
        error_msg = str(error) if error else None
        error_tb = None
        if error and error.__traceback__ is not None:
            frames = []
            tb = error.__traceback__
            while tb is not None:
                frame = tb.tb_frame
                code = frame.f_code
                frame_locals = {}
                for key, value in frame.f_locals.items():
                    if key.startswith("__"):
                        continue
                    try:
                        repr_value = repr(value)
                        frame_locals[key] = (
                            repr_value[:MAX_REPR_LENGTH] + "..."
                            if len(repr_value) > MAX_REPR_LENGTH
                            else repr_value
                        )
                    except Exception as repr_error:
                        frame_locals[key] = (
                            f"<{type(value).__name__} "
                            f"(repr error: {repr_error})>"
                        )

                frames.append(
                    {
                        "filename": code.co_filename,
                        "lineno": tb.tb_lineno,
                        "name": code.co_name,
                        "line": linecache.getline(
                            code.co_filename, tb.tb_lineno
                        ).strip(),
                        "locals": frame_locals,
                    }
                )
                tb = tb.tb_next
            error_tb = json.dumps(
                {
                    "exc_type": type(error).__name__,
                    "exc_value": str(error),
                    "frames": frames,
                }
            )
        module_path = spec.locator.module_path
        file_path = str(module_path) if module_path else None
        tags: set[str] = set(spec.tags)
        with self._connect() as conn:
            conn.execute(
                EXECUTION_INSERT_SQL,
                (
                    str(execution.execution_id),
                    str(run_id),
                    str(parent_id) if parent_id is not None else None,
                    spec.locator.function_name,
                    file_path,
                    spec.locator.class_name,
                    str(spec.case_id) if spec.case_id else None,
                    spec.suffix,
                    json.dumps(list(tags)) if tags else None,
                    spec.skip_reason,
                    spec.xfail_reason,
                    execution.status.value,
                    execution.duration_ms,
                    error_msg,
                    error_tb,
                ),
            )
            for assertion in execution.result.assertion_results:
                assertion_id = self._save_assertion(
                    conn, run_id, execution.execution_id, None, assertion
                )
                for predicate in assertion.predicate_results:
                    self._save_predicate(conn, run_id, assertion_id, predicate)

    def link_executions(
        self,
        parent_id: UUID,
        child_ids: list[UUID],
    ) -> None:
        """Attach already-persisted child rows to a persisted parent."""
        if not child_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE test_executions
                SET parent_id = ?
                WHERE execution_id = ?
                """,
                [(str(parent_id), str(child_id)) for child_id in child_ids],
            )

    def finish_run(self, run: Run) -> None:
        """Persist final run summary, metrics, and retention pruning."""
        with self._connect() as conn:
            conn.execute(
                RUN_UPDATE_SQL,
                (
                    run.end_time.isoformat() if run.end_time else None,
                    run.result.total_duration_ms,
                    run.result.passed,
                    run.result.failed,
                    run.result.errors,
                    run.result.skipped,
                    run.result.xfailed,
                    run.result.xpassed,
                    run.result.total,
                    int(run.result.stopped_early),
                    json.dumps(run.environment.model_dump()),
                    str(run.run_id),
                ),
            )
            for metric_result in run.result.metric_results:
                value = metric_result.value
                value_real: float | None = None
                value_json: str | None = None

                if isinstance(value, (int, float)) and not isinstance(
                    value, bool
                ):
                    value_real = float(value)
                else:
                    value_json = json.dumps(value)

                meta = metric_result.metadata
                ident = meta.identity
                consumers_json = None
                if meta.consumers:
                    consumers: list[dict[str, object]] = []
                    for consumer in meta.consumers:
                        locator = consumer.locator
                        module_path = locator.module_path
                        item: dict[str, object] = {
                            "kind": "spec",
                            "name": locator.function_name,
                            "module_path": None
                            if module_path is None
                            else str(module_path),
                            "class_name": locator.class_name,
                        }
                        if isinstance(consumer, ResourceSpec):
                            item["kind"] = "resource"
                            item["scope"] = _scope_to_storage_value(
                                consumer.scope
                            )
                        elif isinstance(consumer, TestSpec):
                            item["kind"] = "test"
                            item["suffix"] = consumer.suffix
                            item["case_id"] = (
                                None
                                if consumer.case_id is None
                                else str(consumer.case_id)
                            )
                        consumers.append(item)
                    consumers_json = json.dumps(consumers)

                direct_providers_json = None
                if meta.direct_providers:
                    direct_providers_json = json.dumps(
                        [
                            {
                                "name": item.locator.function_name,
                                "scope": _scope_to_storage_value(item.scope),
                                "provider_path": None
                                if item.locator.module_path is None
                                else str(item.locator.module_path),
                                "provider_dir": None
                                if item.locator.module_path is None
                                else str(item.locator.module_path.parent),
                            }
                            for item in meta.direct_providers
                        ]
                    )
                cursor = conn.execute(
                    METRIC_INSERT_SQL,
                    (
                        str(run.run_id),
                        ident.locator.function_name,
                        _scope_to_storage_value(ident.scope),
                        value_real,
                        value_json,
                        meta.first_item_recorded_at.isoformat()
                        if meta.first_item_recorded_at
                        else None,
                        meta.last_item_recorded_at.isoformat()
                        if meta.last_item_recorded_at
                        else None,
                        consumers_json,
                        ident.locator.function_name,
                        _scope_to_storage_value(ident.scope),
                        None
                        if ident.locator.module_path is None
                        else str(ident.locator.module_path),
                        None
                        if ident.locator.module_path is None
                        else str(ident.locator.module_path.parent),
                        direct_providers_json,
                    ),
                )
                metric_id = cast("int", cursor.lastrowid)
                for assertion in metric_result.assertion_results:
                    assertion_id = self._save_assertion(
                        conn=conn,
                        run_id=run.run_id,
                        execution_id=None,
                        metric_id=metric_id,
                        assertion=assertion,
                    )
                    for predicate in assertion.predicate_results:
                        self._save_predicate(
                            conn=conn,
                            run_id=run.run_id,
                            assertion_id=assertion_id,
                            predicate=predicate,
                        )
            conn.execute(
                """
                DELETE FROM runs WHERE run_id IN (
                    SELECT run_id FROM runs
                    ORDER BY start_time DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (MAX_STORED_RUNS,),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _record_tree(self, test: ExecutableTest) -> None:
        child_ids = [child.execution_id for child in test.children]
        if child_ids:
            self._children_by_parent[test.execution_id] = child_ids
            for child_id in child_ids:
                self._parents_by_child[child_id] = test.execution_id
        for child in test.children:
            self._record_tree(child)

    def _save_assertion(
        self,
        conn: sqlite3.Connection,
        run_id: UUID,
        execution_id: UUID | None,
        metric_id: int | None,
        assertion: AssertionResult,
    ) -> int:
        cursor = conn.execute(
            ASSERTION_INSERT_SQL,
            (
                str(run_id),
                str(execution_id) if execution_id else None,
                metric_id,
                json.dumps(asdict(assertion.expression_repr)),
                int(assertion.passed),
                assertion.error_message,
            ),
        )
        return cast("int", cursor.lastrowid)

    def _save_predicate(
        self,
        conn: sqlite3.Connection,
        run_id: UUID,
        assertion_id: int,
        predicate: PredicateResult,
    ) -> None:
        conn.execute(
            PREDICATE_INSERT_SQL,
            (
                str(run_id),
                assertion_id,
                predicate.name,
                predicate.actual,
                predicate.reference,
                int(predicate.strict),
                predicate.confidence,
                int(predicate.value),
                predicate.message,
            ),
        )
