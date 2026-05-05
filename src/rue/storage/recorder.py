"""Run event processor that records Rue runs into Turso."""

from __future__ import annotations

import json
import linecache
from typing import TYPE_CHECKING
from uuid import UUID

import turso

from rue.assertions.models import AssertionResult
from rue.events import RunEventsProcessor
from rue.models import Spec
from rue.predicates.models import PredicateResult
from rue.resources import ResourceSpec, Scope
from rue.storage.store import TursoRunStore
from rue.testing.models.spec import TestSpec


if TYPE_CHECKING:
    from collections.abc import Callable

    from rue.config import Config
    from rue.testing.execution.executable import ExecutableTest
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import ExecutedRun


MAX_REPR_LENGTH = 2000
MAX_TRANSACTION_ATTEMPTS = 3


def _scope_value(scope: Scope | str) -> str:
    return scope.value if isinstance(scope, Scope) else str(scope)


class TursoRunRecorder(RunEventsProcessor):
    """Persists run lifecycle events into Turso."""

    def __init__(self) -> None:
        self.store = TursoRunStore()
        self._conn: turso.Connection | None = None
        self._parents_by_child: dict[UUID, UUID] = {}
        self._children_by_parent: dict[UUID, list[UUID]] = {}
        self._completed: set[UUID] = set()

    @property
    def path(self):
        return self.store.path

    def configure(self, config: Config) -> None:
        self.store = TursoRunStore(config.database_path)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def on_run_start(self, run: ExecutedRun) -> None:
        self._parents_by_child = {}
        self._children_by_parent = {}
        self._completed = set()
        self.store.initialize()
        self._conn = self.store.connect()
        self.start_run(run)

    async def on_tests_ready(
        self,
        tests: list[ExecutableTest],
        run: ExecutedRun,
    ) -> None:
        _ = run
        for test in tests:
            self._record_tree(test)

    async def on_execution_complete(
        self,
        execution: ExecutedTest,
        run: ExecutedRun,
    ) -> None:
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

    async def on_run_complete(self, run: ExecutedRun) -> None:
        self.finish_run(run)

    def start_run(self, run: ExecutedRun) -> None:
        environment = run.environment

        def write(conn: turso.Connection) -> None:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, start_time, end_time, total_duration_ms,
                    passed, failed, errors, skipped, xfailed, xpassed,
                    total, stopped_early, commit_hash, branch, dirty,
                    python_version, platform, hostname, working_directory,
                    rue_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run.run_id),
                    run.start_time.isoformat(),
                    run.end_time.isoformat() if run.end_time else None,
                    run.result.total_duration_ms,
                    run.result.passed,
                    run.result.failed,
                    run.result.errors,
                    run.result.skipped,
                    run.result.xfailed,
                    run.result.xpassed,
                    run.result.total,
                    run.result.stopped_early,
                    environment.commit_hash,
                    environment.branch,
                    environment.dirty,
                    environment.python_version,
                    environment.platform,
                    environment.hostname,
                    environment.working_directory,
                    environment.rue_version,
                ),
            )

        self._write(write)

    def record_execution(
        self,
        run_id: UUID,
        execution: ExecutedTest,
        parent_id: UUID | None = None,
    ) -> None:
        spec = execution.definition.spec
        error = execution.result.error
        module_path = spec.locator.module_path

        def write(conn: turso.Connection) -> None:
            conn.execute(
                """
                INSERT INTO executions (
                    execution_id, run_id, parent_id, function_name,
                    module_path, class_name, is_async, case_id, suffix,
                    collection_index, skip_reason, xfail_reason, xfail_strict,
                    status, duration_ms, error_type, error_message,
                    error_traceback
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(execution.execution_id),
                    str(run_id),
                    str(parent_id) if parent_id is not None else None,
                    spec.locator.function_name,
                    str(module_path) if module_path else None,
                    spec.locator.class_name,
                    spec.is_async,
                    str(spec.case_id) if spec.case_id else None,
                    spec.suffix,
                    spec.collection_index,
                    spec.skip_reason,
                    spec.xfail_reason,
                    spec.xfail_strict,
                    execution.status.value,
                    execution.duration_ms,
                    type(error).__name__ if error else None,
                    str(error) if error else None,
                    self._traceback_json(error),
                ),
            )
            tag_rows = [
                (str(execution.execution_id), tag) for tag in sorted(spec.tags)
            ]
            for row in tag_rows:
                conn.execute(
                    """
                    INSERT INTO execution_tags (execution_id, tag)
                    VALUES (?, ?)
                    """,
                    row,
                )
            for assertion in execution.result.assertion_results:
                assertion_id = self._save_assertion(
                    conn, run_id, execution.execution_id, None, assertion
                )
                for predicate in assertion.predicate_results:
                    self._save_predicate(conn, run_id, assertion_id, predicate)

        self._write(write)

    def link_executions(
        self,
        parent_id: UUID,
        child_ids: list[UUID],
    ) -> None:
        if not child_ids:
            return

        def write(conn: turso.Connection) -> None:
            for child_id in child_ids:
                conn.execute(
                    """
                    UPDATE executions
                    SET parent_id = ?
                    WHERE execution_id = ?
                    """,
                    (str(parent_id), str(child_id)),
                )

        self._write(write)

    def finish_run(self, run: ExecutedRun) -> None:
        def write(conn: turso.Connection) -> None:
            conn.execute(
                """
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
                    commit_hash = ?,
                    branch = ?,
                    dirty = ?,
                    python_version = ?,
                    platform = ?,
                    hostname = ?,
                    working_directory = ?,
                    rue_version = ?
                WHERE run_id = ?
                """,
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
                    run.result.stopped_early,
                    run.environment.commit_hash,
                    run.environment.branch,
                    run.environment.dirty,
                    run.environment.python_version,
                    run.environment.platform,
                    run.environment.hostname,
                    run.environment.working_directory,
                    run.environment.rue_version,
                    str(run.run_id),
                ),
            )
            for metric in run.result.metric_results:
                metric_id = self._save_metric(conn, run.run_id, metric)
                for assertion in metric.assertion_results:
                    assertion_id = self._save_assertion(
                        conn, run.run_id, None, metric_id, assertion
                    )
                    for predicate in assertion.predicate_results:
                        self._save_predicate(
                            conn, run.run_id, assertion_id, predicate
                        )

        self._write(write)

    def _connection(self) -> turso.Connection:
        if self._conn is None:
            self.store.initialize()
            self._conn = self.store.connect()
        return self._conn

    def _write(self, write: Callable[[turso.Connection], None]) -> None:
        conn = self._connection()
        for attempt in range(MAX_TRANSACTION_ATTEMPTS):
            conn.execute("BEGIN CONCURRENT")
            try:
                write(conn)
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

    def _save_metric(
        self,
        conn: turso.Connection,
        run_id: UUID,
        metric,
    ) -> int:
        value = metric.value
        value_integer = None
        value_real = None
        value_boolean = None
        value_json = None
        if isinstance(value, bool):
            value_boolean = value
        elif isinstance(value, int):
            value_integer = value
        elif isinstance(value, float):
            value_real = value
        else:
            value_json = json.dumps(value)

        meta = metric.metadata
        identity = meta.identity
        module_path = identity.locator.module_path
        row = conn.execute(
            """
            INSERT INTO metrics (
                run_id, name, scope, provider_path, provider_dir,
                value_integer, value_real, value_boolean, value_json,
                first_recorded_at, last_recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING metric_id
            """,
            (
                str(run_id),
                identity.locator.function_name,
                _scope_value(identity.scope),
                str(module_path) if module_path else None,
                str(module_path.parent) if module_path else None,
                value_integer,
                value_real,
                value_boolean,
                value_json,
                meta.first_item_recorded_at.isoformat()
                if meta.first_item_recorded_at
                else None,
                meta.last_item_recorded_at.isoformat()
                if meta.last_item_recorded_at
                else None,
            ),
        ).fetchone()
        metric_id = int(row["metric_id"])
        for consumer in meta.consumers:
            self._save_metric_consumer(conn, metric_id, consumer)
        dependency_rows = [
            (
                metric_id,
                provider.locator.function_name,
                str(provider.locator.module_path)
                if provider.locator.module_path
                else None,
                _scope_value(provider.scope),
            )
            for provider in meta.direct_providers
        ]
        for row in dependency_rows:
            conn.execute(
                """
                INSERT INTO metric_dependencies (
                    metric_id, function_name, module_path, scope
                ) VALUES (?, ?, ?, ?)
                """,
                row,
            )
        return metric_id

    def _save_metric_consumer(
        self,
        conn: turso.Connection,
        metric_id: int,
        consumer: Spec,
    ) -> None:
        locator = consumer.locator
        kind = "spec"
        scope = None
        suffix = None
        case_id = None
        if isinstance(consumer, ResourceSpec):
            kind = "resource"
            scope = _scope_value(consumer.scope)
        elif isinstance(consumer, TestSpec):
            kind = "test"
            suffix = consumer.suffix
            case_id = str(consumer.case_id) if consumer.case_id else None

        conn.execute(
            """
            INSERT INTO metric_consumers (
                metric_id, kind, function_name, module_path, class_name,
                scope, suffix, case_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metric_id,
                kind,
                locator.function_name,
                str(locator.module_path) if locator.module_path else None,
                locator.class_name,
                scope,
                suffix,
                case_id,
            ),
        )

    def _save_assertion(
        self,
        conn: turso.Connection,
        run_id: UUID,
        execution_id: UUID | None,
        metric_id: int | None,
        assertion: AssertionResult,
    ) -> int:
        expression = assertion.expression_repr
        row = conn.execute(
            """
            INSERT INTO assertions (
                run_id, execution_id, metric_id, expression, lines_above,
                lines_below, resolved_args, col_offset, passed, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING assertion_id
            """,
            (
                str(run_id),
                str(execution_id) if execution_id else None,
                metric_id,
                expression.expr,
                expression.lines_above,
                expression.lines_below,
                json.dumps(expression.resolved_args),
                expression.col_offset,
                assertion.passed,
                assertion.error_message,
            ),
        ).fetchone()
        return int(row["assertion_id"])

    def _save_predicate(
        self,
        conn: turso.Connection,
        run_id: UUID,
        assertion_id: int,
        predicate: PredicateResult,
    ) -> None:
        conn.execute(
            """
            INSERT INTO predicates (
                run_id, assertion_id, predicate_name, actual, reference,
                strict, confidence, value, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(run_id),
                assertion_id,
                predicate.name,
                predicate.actual,
                predicate.reference,
                predicate.strict,
                predicate.confidence,
                predicate.value,
                predicate.message,
            ),
        )

    def _traceback_json(self, error: BaseException | None) -> str | None:
        if error is None or error.__traceback__ is None:
            return None

        frames = []
        tb = error.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            frame_locals = {}
            for key, value in tb.tb_frame.f_locals.items():
                if key.startswith("__"):
                    continue
                text = repr(value)
                frame_locals[key] = (
                    f"{text[:MAX_REPR_LENGTH]}..."
                    if len(text) > MAX_REPR_LENGTH
                    else text
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
        return json.dumps(
            {
                "exc_type": type(error).__name__,
                "exc_value": str(error),
                "frames": frames,
            }
        )


__all__ = ["TursoRunRecorder"]
