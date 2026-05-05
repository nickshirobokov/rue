"""Storage-specific view models."""

# ruff: noqa: D101,D102

from __future__ import annotations

import json
import linecache
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING
from uuid import UUID

import turso

from rue.models import Spec
from rue.resources import ResourceSpec, Scope
from rue.testing.models.spec import TestSpec


if TYPE_CHECKING:
    from rue.assertions.models import AssertionResult
    from rue.predicates.models import PredicateResult
    from rue.resources.metrics.models import MetricResult
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import ExecutedRun


MAX_REPR_LENGTH = 2000


def _scope_value(scope: Scope | str) -> str:
    return scope.value if isinstance(scope, Scope) else str(scope)


@dataclass(frozen=True, slots=True)
class StoredRunView:
    run_id: str
    start_time: str
    end_time: str | None
    total_duration_ms: float
    passed: int
    failed: int
    errors: int
    skipped: int
    xfailed: int
    xpassed: int
    total: int
    stopped_early: bool
    commit_hash: str | None
    branch: str | None
    dirty: bool | None
    python_version: str
    platform: str
    hostname: str
    working_directory: str
    rue_version: str
    metrics: tuple[StoredMetricView, ...] = ()

    @classmethod
    def from_run(cls, run: ExecutedRun) -> StoredRunView:
        environment = run.environment
        return cls(
            run_id=str(run.run_id),
            start_time=run.start_time.isoformat(),
            end_time=run.end_time.isoformat() if run.end_time else None,
            total_duration_ms=run.result.total_duration_ms,
            passed=run.result.passed,
            failed=run.result.failed,
            errors=run.result.errors,
            skipped=run.result.skipped,
            xfailed=run.result.xfailed,
            xpassed=run.result.xpassed,
            total=run.result.total,
            stopped_early=run.result.stopped_early,
            commit_hash=environment.commit_hash,
            branch=environment.branch,
            dirty=environment.dirty,
            python_version=environment.python_version,
            platform=environment.platform,
            hostname=environment.hostname,
            working_directory=environment.working_directory,
            rue_version=environment.rue_version,
            metrics=tuple(
                StoredMetricView.from_metric(run.run_id, metric)
                for metric in run.result.metric_results
            ),
        )

    def _insert_values(self) -> tuple[object, ...]:
        return (
            self.run_id,
            self.start_time,
            self.end_time,
            self.total_duration_ms,
            self.passed,
            self.failed,
            self.errors,
            self.skipped,
            self.xfailed,
            self.xpassed,
            self.total,
            self.stopped_early,
            self.commit_hash,
            self.branch,
            self.dirty,
            self.python_version,
            self.platform,
            self.hostname,
            self.working_directory,
            self.rue_version,
        )

    def _update_values(self) -> tuple[object, ...]:
        return (
            self.end_time,
            self.total_duration_ms,
            self.passed,
            self.failed,
            self.errors,
            self.skipped,
            self.xfailed,
            self.xpassed,
            self.total,
            self.stopped_early,
            self.commit_hash,
            self.branch,
            self.dirty,
            self.python_version,
            self.platform,
            self.hostname,
            self.working_directory,
            self.rue_version,
            self.run_id,
        )

    def insert(self, conn: turso.Connection) -> None:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, start_time, end_time, total_duration_ms,
                passed, failed, errors, skipped, xfailed, xpassed,
                total, stopped_early, commit_hash, branch, dirty,
                python_version, platform, hostname, working_directory,
                rue_version
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            self._insert_values(),
        )

    def update(self, conn: turso.Connection) -> None:
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
            self._update_values(),
        )

    def insert_metrics(self, conn: turso.Connection) -> None:
        for metric in self.metrics:
            metric.insert(conn)

    def finish(self, conn: turso.Connection) -> None:
        self.update(conn)
        self.insert_metrics(conn)


@dataclass(frozen=True, slots=True)
class StoredExecutionView:
    execution_id: str
    run_id: str
    parent_id: str | None
    function_name: str
    module_path: str | None
    class_name: str | None
    is_async: bool
    case_id: str | None
    suffix: str | None
    collection_index: int
    skip_reason: str | None
    xfail_reason: str | None
    xfail_strict: bool
    status: str
    duration_ms: float
    error_type: str | None
    error_message: str | None
    error_traceback: str | None
    tags: tuple[str, ...]
    assertions: tuple[_StoredAssertionRow, ...] = ()

    @classmethod
    def from_execution(
        cls,
        run_id: UUID,
        execution: ExecutedTest,
        parent_id: UUID | None = None,
    ) -> StoredExecutionView:
        spec = execution.definition.spec
        error = execution.result.error
        module_path = spec.locator.module_path
        traceback = _StoredTracebackPayload.from_error(error)
        return cls(
            execution_id=str(execution.execution_id),
            run_id=str(run_id),
            parent_id=str(parent_id) if parent_id is not None else None,
            function_name=spec.locator.function_name,
            module_path=str(module_path) if module_path else None,
            class_name=spec.locator.class_name,
            is_async=spec.is_async,
            case_id=str(spec.case_id) if spec.case_id else None,
            suffix=spec.suffix,
            collection_index=spec.collection_index,
            skip_reason=spec.skip_reason,
            xfail_reason=spec.xfail_reason,
            xfail_strict=spec.xfail_strict,
            status=execution.status.value,
            duration_ms=execution.duration_ms,
            error_type=type(error).__name__ if error else None,
            error_message=str(error) if error else None,
            error_traceback=None if traceback is None else traceback.json,
            tags=tuple(sorted(spec.tags)),
            assertions=tuple(
                _StoredAssertionRow.from_result(
                    run_id,
                    assertion,
                    execution_id=execution.execution_id,
                )
                for assertion in execution.result.assertion_results
            ),
        )

    def _insert_values(self) -> tuple[object, ...]:
        return (
            self.execution_id,
            self.run_id,
            self.parent_id,
            self.function_name,
            self.module_path,
            self.class_name,
            self.is_async,
            self.case_id,
            self.suffix,
            self.collection_index,
            self.skip_reason,
            self.xfail_reason,
            self.xfail_strict,
            self.status,
            self.duration_ms,
            self.error_type,
            self.error_message,
            self.error_traceback,
        )

    def _tag_rows(self) -> tuple[tuple[str, str], ...]:
        return tuple((self.execution_id, tag) for tag in self.tags)

    def insert(self, conn: turso.Connection) -> None:
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
            self._insert_values(),
        )
        for row in self._tag_rows():
            conn.execute(
                """
                INSERT INTO execution_tags (execution_id, tag)
                VALUES (?, ?)
                """,
                row,
            )
        for assertion in self.assertions:
            assertion.insert(conn)


@dataclass(frozen=True, slots=True)
class StoredMetricView:
    run_id: str
    name: str
    scope: str
    provider_path: str | None
    provider_dir: str | None
    value_integer: int | None
    value_real: float | None
    value_boolean: bool | None
    value_json: str | None
    first_recorded_at: str | None
    last_recorded_at: str | None
    consumers: tuple[_StoredMetricConsumerRow, ...]
    direct_providers: tuple[_StoredMetricDependencyRow, ...]
    assertions: tuple[_StoredAssertionRow, ...]

    @classmethod
    def from_metric(
        cls,
        run_id: UUID,
        metric: MetricResult,
    ) -> StoredMetricView:
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
        return cls(
            run_id=str(run_id),
            name=identity.locator.function_name,
            scope=_scope_value(identity.scope),
            provider_path=str(module_path) if module_path else None,
            provider_dir=str(module_path.parent) if module_path else None,
            value_integer=value_integer,
            value_real=value_real,
            value_boolean=value_boolean,
            value_json=value_json,
            first_recorded_at=meta.first_item_recorded_at.isoformat()
            if meta.first_item_recorded_at
            else None,
            last_recorded_at=meta.last_item_recorded_at.isoformat()
            if meta.last_item_recorded_at
            else None,
            consumers=tuple(
                _StoredMetricConsumerRow.from_spec(None, consumer)
                for consumer in meta.consumers
            ),
            direct_providers=tuple(
                _StoredMetricDependencyRow.from_spec(None, provider)
                for provider in meta.direct_providers
            ),
            assertions=tuple(
                _StoredAssertionRow.from_result(
                    run_id,
                    assertion,
                    metric_id=None,
                )
                for assertion in metric.assertion_results
            ),
        )

    def _insert_values(self) -> tuple[object, ...]:
        return (
            self.run_id,
            self.name,
            self.scope,
            self.provider_path,
            self.provider_dir,
            self.value_integer,
            self.value_real,
            self.value_boolean,
            self.value_json,
            self.first_recorded_at,
            self.last_recorded_at,
        )

    def insert(self, conn: turso.Connection) -> int:
        row = conn.execute(
            """
            INSERT INTO metrics (
                run_id, name, scope, provider_path, provider_dir,
                value_integer, value_real, value_boolean, value_json,
                first_recorded_at, last_recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING metric_id
            """,
            self._insert_values(),
        ).fetchone()
        metric_id = int(row["metric_id"])
        for consumer in self.consumers:
            consumer.insert(conn, metric_id)
        for provider in self.direct_providers:
            provider.insert(conn, metric_id)
        for assertion in self.assertions:
            assertion.insert(conn, metric_id=metric_id)
        return metric_id


@dataclass(frozen=True, slots=True)
class _StoredMetricConsumerRow:
    metric_id: int | None
    kind: str
    function_name: str
    module_path: str | None
    class_name: str | None
    scope: str | None
    suffix: str | None
    case_id: str | None

    @classmethod
    def from_spec(
        cls,
        metric_id: int | None,
        consumer: Spec,
    ) -> _StoredMetricConsumerRow:
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

        return cls(
            metric_id=metric_id,
            kind=kind,
            function_name=locator.function_name,
            module_path=(
                str(locator.module_path) if locator.module_path else None
            ),
            class_name=locator.class_name,
            scope=scope,
            suffix=suffix,
            case_id=case_id,
        )

    def _values(self, metric_id: int | None = None) -> tuple[object, ...]:
        metric_ref = self.metric_id if self.metric_id is not None else metric_id
        assert metric_ref is not None
        return (
            metric_ref,
            self.kind,
            self.function_name,
            self.module_path,
            self.class_name,
            self.scope,
            self.suffix,
            self.case_id,
        )

    def insert(
        self,
        conn: turso.Connection,
        metric_id: int | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO metric_consumers (
                metric_id, kind, function_name, module_path, class_name,
                scope, suffix, case_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._values(metric_id),
        )


@dataclass(frozen=True, slots=True)
class _StoredMetricDependencyRow:
    metric_id: int | None
    function_name: str
    module_path: str | None
    scope: str

    @classmethod
    def from_spec(
        cls,
        metric_id: int | None,
        provider: ResourceSpec,
    ) -> _StoredMetricDependencyRow:
        return cls(
            metric_id=metric_id,
            function_name=provider.locator.function_name,
            module_path=str(provider.locator.module_path)
            if provider.locator.module_path
            else None,
            scope=_scope_value(provider.scope),
        )

    def _values(self, metric_id: int | None = None) -> tuple[object, ...]:
        metric_ref = self.metric_id if self.metric_id is not None else metric_id
        assert metric_ref is not None
        return (
            metric_ref,
            self.function_name,
            self.module_path,
            self.scope,
        )

    def insert(
        self,
        conn: turso.Connection,
        metric_id: int | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO metric_dependencies (
                metric_id, function_name, module_path, scope
            ) VALUES (?, ?, ?, ?)
            """,
            self._values(metric_id),
        )


@dataclass(frozen=True, slots=True)
class _StoredAssertionRow:
    run_id: str
    execution_id: str | None
    metric_id: int | None
    expression: str
    lines_above: str
    lines_below: str
    resolved_args: str
    col_offset: int
    passed: bool
    error_message: str | None
    predicates: tuple[_StoredPredicateRow, ...] = ()

    @classmethod
    def from_result(
        cls,
        run_id: UUID,
        assertion: AssertionResult,
        execution_id: UUID | None = None,
        metric_id: int | None = None,
    ) -> _StoredAssertionRow:
        expression = assertion.expression_repr
        return cls(
            run_id=str(run_id),
            execution_id=str(execution_id) if execution_id else None,
            metric_id=metric_id,
            expression=expression.expr,
            lines_above=expression.lines_above,
            lines_below=expression.lines_below,
            resolved_args=json.dumps(expression.resolved_args),
            col_offset=expression.col_offset,
            passed=assertion.passed,
            error_message=assertion.error_message,
            predicates=tuple(
                _StoredPredicateRow.from_result(run_id, None, predicate)
                for predicate in assertion.predicate_results
            ),
        )

    def _values(self, metric_id: int | None = None) -> tuple[object, ...]:
        metric_ref = self.metric_id if self.metric_id is not None else metric_id
        return (
            self.run_id,
            self.execution_id,
            metric_ref,
            self.expression,
            self.lines_above,
            self.lines_below,
            self.resolved_args,
            self.col_offset,
            self.passed,
            self.error_message,
        )

    def insert(
        self,
        conn: turso.Connection,
        metric_id: int | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO assertions (
                run_id, execution_id, metric_id, expression, lines_above,
                lines_below, resolved_args, col_offset, passed, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING assertion_id
            """,
            self._values(metric_id),
        ).fetchone()
        assertion_id = int(row["assertion_id"])
        for predicate in self.predicates:
            predicate.insert(conn, assertion_id)
        return assertion_id


@dataclass(frozen=True, slots=True)
class _StoredPredicateRow:
    run_id: str
    assertion_id: int | None
    predicate_name: str
    actual: str
    reference: str
    strict: bool
    confidence: float
    value: bool
    message: str | None

    @classmethod
    def from_result(
        cls,
        run_id: UUID,
        assertion_id: int | None,
        predicate: PredicateResult,
    ) -> _StoredPredicateRow:
        return cls(
            run_id=str(run_id),
            assertion_id=assertion_id,
            predicate_name=predicate.name,
            actual=predicate.actual,
            reference=predicate.reference,
            strict=predicate.strict,
            confidence=predicate.confidence,
            value=predicate.value,
            message=predicate.message,
        )

    def _values(self, assertion_id: int | None = None) -> tuple[object, ...]:
        assertion_ref = (
            self.assertion_id
            if self.assertion_id is not None
            else assertion_id
        )
        assert assertion_ref is not None
        return (
            self.run_id,
            assertion_ref,
            self.predicate_name,
            self.actual,
            self.reference,
            self.strict,
            self.confidence,
            self.value,
            self.message,
        )

    def insert(
        self,
        conn: turso.Connection,
        assertion_id: int | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO predicates (
                run_id, assertion_id, predicate_name, actual, reference,
                strict, confidence, value, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._values(assertion_id),
        )


@dataclass(frozen=True, slots=True)
class _StoredTracebackPayload:
    exc_type: str
    exc_value: str
    frames: tuple[dict[str, object], ...]

    @classmethod
    def from_error(
        cls,
        error: BaseException | None,
        max_repr_length: int = MAX_REPR_LENGTH,
    ) -> _StoredTracebackPayload | None:
        if error is None or error.__traceback__ is None:
            return None

        frames = []
        tb: TracebackType | None = error.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            frame_locals = {}
            for key, value in tb.tb_frame.f_locals.items():
                if key.startswith("__"):
                    continue
                text = repr(value)
                frame_locals[key] = (
                    f"{text[:max_repr_length]}..."
                    if len(text) > max_repr_length
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
        return cls(
            exc_type=type(error).__name__,
            exc_value=str(error),
            frames=tuple(frames),
        )

    @property
    def payload(self) -> dict[str, object]:
        return {
            "exc_type": self.exc_type,
            "exc_value": self.exc_value,
            "frames": list(self.frames),
        }

    @property
    def json(self) -> str:
        return json.dumps(self.payload)


__all__ = [
    "MAX_REPR_LENGTH",
    "StoredExecutionView",
    "StoredMetricView",
    "StoredRunView",
]
