"""SQLite storage backend for Rue test runs."""

import json
import linecache
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from rue.assertions.base import AssertionResult
from rue.models import Locator, Spec
from rue.predicates.models import PredicateResult
from rue.resources import ResourceSpec, Scope
from rue.resources.metrics.base import (
    CalculatedValue,
    MetricMetadata,
    MetricResult,
)
from rue.storage.base import Store
from rue.storage.sqlite.migrations import MigrationError, MigrationRunner
from rue.testing.models import (
    ExecutedTest,
    LoadedTestDef,
    Run,
    RunEnvironment,
    RunResult,
    TestStatus,
)
from rue.testing.models.result import TestResult
from rue.testing.models.spec import TestSpec


DEFAULT_DB_NAME = ".rue/rue.db"
MAX_STORED_RUNS = 5

MAX_REPR_LENGTH = 2000  # Max length for repr of local variables

RUN_INSERT_SQL = """
    INSERT INTO runs (
        run_id, start_time, end_time, total_duration_ms,
        passed, failed, errors, skipped, xfailed, xpassed,
        total, stopped_early, environment_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def find_project_root() -> Path:
    """Find project root by searching for pyproject.toml."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return cwd


class SQLiteStore(Store):
    """SQLite-based storage for Rue test runs."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = find_project_root() / DEFAULT_DB_NAME
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        runner = MigrationRunner(self.path)

        if not self.path.exists():
            runner.migrate()
            return

        if not runner.needs_migration():
            return

        if runner.can_migrate():
            runner.migrate()
        else:
            raise MigrationError(
                current_version=runner.get_current_version(),
                target_version=runner.get_target_version(),
                db_path=self.path,
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _format_traceback(self, error: BaseException) -> str | None:
        if error.__traceback__ is None:
            return None

        # Serialize traceback frames (including locals) so runs can be replayed later.
        frames = []
        tb = error.__traceback__

        while tb is not None:
            frame = tb.tb_frame
            code = frame.f_code

            # Store a compact repr for locals to keep the payload small.
            frame_locals = {
                k: self._safe_repr(v)
                for k, v in frame.f_locals.items()
                if not k.startswith("__")
            }

            frames.append(
                {
                    "filename": code.co_filename,
                    "lineno": tb.tb_lineno,
                    "name": code.co_name,
                    # Cache source line at capture time in case files change later.
                    "line": linecache.getline(
                        code.co_filename, tb.tb_lineno
                    ).strip(),
                    "locals": frame_locals,
                }
            )

            tb = tb.tb_next

        # JSON format mirrors rich.traceback so we can reconstruct a display later.
        # But should be usable even outside of Rich.
        return json.dumps(
            {
                "exc_type": type(error).__name__,
                "exc_value": str(error),
                "frames": frames,
            }
        )

    def _safe_repr(self, value: object) -> str:
        try:
            r = repr(value)
            return (
                r[:MAX_REPR_LENGTH] + "..." if len(r) > MAX_REPR_LENGTH else r
            )
        except Exception as e:
            return f"<{type(value).__name__} (repr error: {e})>"

    def save_run(self, run: Run) -> None:
        """Save a complete test run."""
        with self._connect() as conn:
            run_id = str(run.run_id)
            conn.execute(
                RUN_INSERT_SQL,
                (
                    run_id,
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
                    int(run.result.stopped_early),
                    json.dumps(run.environment.model_dump()),
                ),
            )

            execution_rows: list[tuple[object, ...]] = []
            for execution in run.result.executions:
                self._append_execution_rows(
                    execution_rows,
                    execution,
                    run_id=run_id,
                    parent_id=None,
                )

            if execution_rows:
                conn.executemany(EXECUTION_INSERT_SQL, execution_rows)

            for metric_result in run.result.metric_results:
                metric_id = self._save_metric(conn, run.run_id, metric_result)
                self._save_metric_assertions(
                    conn, run.run_id, metric_result, metric_id
                )

            for execution in run.result.executions:
                self._save_assertions_for_execution(conn, run.run_id, execution)

            self._prune_old_runs(conn)

    def _prune_old_runs(self, conn: sqlite3.Connection) -> None:
        """Delete oldest runs exceeding MAX_STORED_RUNS limit."""
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

    def _save_assertions_for_execution(
        self,
        conn: sqlite3.Connection,
        run_id: UUID,
        execution: ExecutedTest,
    ) -> None:
        for assertion in execution.result.assertion_results:
            assertion_id = self._save_assertion(
                conn, run_id, execution.execution_id, None, assertion
            )
            for predicate in assertion.predicate_results:
                self._save_predicate(conn, run_id, assertion_id, predicate)

        for sub in execution.sub_executions:
            self._save_assertions_for_execution(conn, run_id, sub)

    def _save_metric(
        self,
        conn: sqlite3.Connection,
        run_id: UUID,
        metric: MetricResult,
    ) -> int:
        value = metric.value
        value_real: float | None = None
        value_json: str | None = None

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value_real = float(value)
        else:
            value_json = json.dumps(value)

        meta = metric.metadata
        ident = meta.identity
        cursor = conn.execute(
            METRIC_INSERT_SQL,
            (
                str(run_id),
                ident.locator.function_name,
                ident.scope.value
                if isinstance(ident.scope, Scope)
                else str(ident.scope),
                value_real,
                value_json,
                meta.first_item_recorded_at.isoformat()
                if meta.first_item_recorded_at
                else None,
                meta.last_item_recorded_at.isoformat()
                if meta.last_item_recorded_at
                else None,
                self._to_json_consumers(meta.consumers),
                ident.locator.function_name,
                ident.scope.value
                if isinstance(ident.scope, Scope)
                else str(ident.scope),
                None
                if ident.locator.module_path is None
                else str(ident.locator.module_path),
                None
                if ident.locator.module_path is None
                else str(ident.locator.module_path.parent),
                self._to_json_resource_identities(
                    meta.direct_providers
                ),
            ),
        )
        return cast("int", cursor.lastrowid)

    def _save_metric_assertions(
        self,
        conn: sqlite3.Connection,
        run_id: UUID,
        metric: MetricResult,
        metric_id: int,
    ) -> None:
        """Save assertion results linked to a metric, reusing _save_assertion."""
        for assertion in metric.assertion_results:
            self._save_assertion(
                conn=conn,
                run_id=run_id,
                execution_id=None,
                metric_id=metric_id,
                assertion=assertion,
            )
            for predicate in assertion.predicate_results:
                self._save_predicate(
                    conn=conn,
                    run_id=run_id,
                    assertion_id=metric_id,
                    predicate=predicate,
                )

    def _to_json_consumers(self, consumers: list[Spec]) -> str | None:
        if not consumers:
            return None

        data: list[dict[str, object]] = []
        for consumer in consumers:
            locator = consumer.locator
            module_path = locator.module_path
            item: dict[str, object] = {
                "kind": "spec",
                "name": locator.function_name,
                "module_path": (
                    None if module_path is None else str(module_path)
                ),
                "class_name": locator.class_name,
            }
            if isinstance(consumer, ResourceSpec):
                item["kind"] = "resource"
                item["scope"] = consumer.scope.value
            elif isinstance(consumer, TestSpec):
                item["kind"] = "test"
                item["suffix"] = consumer.suffix
                item["case_id"] = (
                    None if consumer.case_id is None else str(consumer.case_id)
                )
            data.append(item)
        return json.dumps(data)

    def _to_json_resource_identities(
        self, items: list[ResourceSpec]
    ) -> str | None:
        if not items:
            return None
        return json.dumps(
            [
                {
                    "name": item.locator.function_name,
                    "scope": item.scope.value,
                    "provider_path": None
                    if item.locator.module_path is None
                    else str(item.locator.module_path),
                    "provider_dir": None
                    if item.locator.module_path is None
                    else str(item.locator.module_path.parent),
                }
                for item in items
            ]
        )

    def _append_execution_rows(
        self,
        rows: list[tuple[object, ...]],
        execution: ExecutedTest,
        *,
        run_id: str,
        parent_id: str | None,
    ) -> None:
        spec = execution.definition.spec
        error = execution.result.error
        error_msg = str(error) if error else None
        error_tb = self._format_traceback(error) if error else None
        module_path = spec.locator.module_path
        file_path = str(module_path) if module_path else None
        tags: set[str] = set(spec.tags)
        execution_id = str(execution.execution_id)

        rows.append(
            (
                execution_id,
                run_id,
                parent_id,
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
            )
        )

        for child in execution.sub_executions:
            self._append_execution_rows(
                rows,
                child,
                run_id=run_id,
                parent_id=execution_id,
            )

    def get_run(self, run_id: UUID) -> Run | None:
        """Retrieve a test run by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()

            if not row:
                return None

            return self._row_to_run(conn, row)

    def list_runs(self, limit: int = 10) -> list[Run]:
        """List recent runs, ordered by start_time descending."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY start_time DESC LIMIT ?", (limit,)
            ).fetchall()

            return [self._row_to_run(conn, row) for row in rows]

    def get_assertions_for_execution(self, execution_id: UUID) -> list[dict]:
        """Get all assertions for a specific test execution."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM assertions WHERE test_execution_id = ?",
                (str(execution_id),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_assertions_for_run(self, run_id: UUID) -> list[dict]:
        """Get all assertions for a specific run."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM assertions WHERE run_id = ?",
                (str(run_id),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_predicates_for_assertion(self, assertion_id: int) -> list[dict]:
        """Get all predicates for a specific assertion."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM predicates WHERE assertion_id = ?",
                (assertion_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def _row_to_run(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Run:
        env_data = (
            json.loads(row["environment_json"])
            if row["environment_json"]
            else {}
        )
        environment = RunEnvironment.model_validate(env_data)

        exec_rows = conn.execute(
            "SELECT * FROM test_executions WHERE run_id = ?",
            (row["run_id"],),
        ).fetchall()

        executions_by_id: dict[str, ExecutedTest] = {}
        for exec_row in exec_rows:
            executions_by_id[exec_row["execution_id"]] = self._row_to_execution(
                exec_row
            )

        executions: list[ExecutedTest] = []
        for exec_row in exec_rows:
            execution = executions_by_id[exec_row["execution_id"]]
            parent_id = exec_row["parent_id"]
            if parent_id:
                executions_by_id[parent_id].sub_executions.append(execution)
            else:
                executions.append(execution)

        metric_rows = conn.execute(
            "SELECT * FROM metrics WHERE run_id = ?",
            (row["run_id"],),
        ).fetchall()
        metric_results = [self._row_to_metric(r) for r in metric_rows]

        result = RunResult(
            executions=executions,
            metric_results=metric_results,
            total_duration_ms=row["total_duration_ms"],
            stopped_early=bool(row["stopped_early"]),
        )

        end_time = None
        if row["end_time"]:
            end_time = datetime.fromisoformat(row["end_time"])

        return Run(
            run_id=UUID(row["run_id"]),
            start_time=datetime.fromisoformat(row["start_time"]),
            end_time=end_time,
            environment=environment,
            result=result,
        )

    def _row_to_execution(self, row: sqlite3.Row) -> ExecutedTest:
        error = (
            Exception(row["error_message"]) if row["error_message"] else None
        )
        tags_json = row["tags_json"]
        tags = set(json.loads(tags_json)) if tags_json else set()

        definition = LoadedTestDef(
            spec=TestSpec(
                locator=Locator(
                    module_path=Path(row["file_path"])
                    if row["file_path"]
                    else Path(),
                    function_name=row["test_name"],
                    class_name=row["class_name"],
                ),
                is_async=False,
                params=(),
                modifiers=(),
                tags=frozenset(tags),
                skip_reason=row["skip_reason"],
                xfail_reason=row["xfail_reason"],
                suffix=row["suffix"],
                case_id=UUID(row["case_id"]) if row["case_id"] else None,
                collection_index=0,
            ),
            fn=lambda: None,
            suite_root=(
                Path(row["file_path"]).parent if row["file_path"] else Path()
            ),
        )

        result = TestResult(
            status=TestStatus(row["status"]),
            duration_ms=row["duration_ms"],
            error=error,
        )

        return ExecutedTest(
            definition=definition,
            result=result,
            execution_id=UUID(row["execution_id"]),
        )

    def _row_to_metric(self, row: sqlite3.Row) -> MetricResult:
        keys = set(row.keys())

        if row["value"] is not None:
            value = cast("CalculatedValue", row["value"])
        elif row["value_json"]:
            value = cast("CalculatedValue", json.loads(row["value_json"]))
        else:
            value = float("nan")

        scope_str = row["scope"]
        scope = (
            Scope(scope_str)
            if scope_str in {s.value for s in Scope}
            else Scope.RUN
        )

        first_at = row["first_recorded_at"]
        last_at = row["last_recorded_at"]
        provider_path = row["provider_path"] if "provider_path" in keys else None
        identity = ResourceSpec(
            locator=Locator(
                module_path=Path(provider_path) if provider_path else None,
                function_name=row["name"],
            ),
            scope=scope,
        )
        direct_providers = self._from_json_resource_identities(
            row["depends_on_metrics_json"]
            if "depends_on_metrics_json" in keys
            else None
        )
        metadata = MetricMetadata(
            first_item_recorded_at=datetime.fromisoformat(first_at)
            if first_at
            else None,
            last_item_recorded_at=datetime.fromisoformat(last_at)
            if last_at
            else None,
            identity=identity,
            consumers=self._from_json_consumers(
                row["consumers_json"] if "consumers_json" in keys else None
            ),
            direct_providers=direct_providers,
        )

        return MetricResult(
            metadata=metadata,
            assertion_results=[],
            value=value,
        )

    def _from_json_consumers(self, json_str: str | None) -> list[Spec]:
        if not json_str:
            return []

        consumers: list[Spec] = []
        for item in json.loads(json_str):
            module_path = item.get("module_path")
            locator = Locator(
                module_path=Path(module_path) if module_path else None,
                function_name=item["name"],
                class_name=item.get("class_name"),
            )
            match item.get("kind"):
                case "resource":
                    consumers.append(
                        ResourceSpec(
                            locator=locator,
                            scope=Scope(item["scope"]),
                        )
                    )
                case "test":
                    case_id = item.get("case_id")
                    consumers.append(
                        TestSpec(
                            locator=locator,
                            is_async=False,
                            params=(),
                            modifiers=(),
                            tags=frozenset(),
                            suffix=item.get("suffix"),
                            case_id=UUID(case_id) if case_id else None,
                            collection_index=0,
                        )
                    )
                case _:
                    consumers.append(Spec(locator=locator))
        return consumers

    def _from_json_resource_identities(
        self, json_str: str | None
    ) -> list[ResourceSpec]:
        if not json_str:
            return []
        return [
            ResourceSpec(
                locator=Locator(
                    module_path=Path(item["provider_path"])
                    if item.get("provider_path")
                    else None,
                    function_name=item["name"],
                ),
                scope=Scope(item["scope"]),
            )
            for item in json.loads(json_str)
        ]
