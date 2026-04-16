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
from rue.predicates.models import PredicateResult
from rue.resources import ResourceSpec, Scope
from rue.resources.metrics.base import (
    CalculatedValue,
    MetricMetadata,
    MetricResult,
)
from rue.storage.base import Store
from rue.storage.sqlite.migrations import MigrationError, MigrationRunner
from rue.testing.models.loaded import LoadedTestDef
from rue.testing.models.result import TestExecution, TestResult, TestStatus
from rue.testing.models.run import Run, RunEnvironment, RunResult
from rue.testing.models.spec import TestLocator, TestSpec


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
        run_id, test_execution_id, name, scope, value, value_json,
        first_recorded_at, last_recorded_at,
        collected_from_tests_json, collected_from_resources_json, collected_from_cases_json,
        collected_from_modules_json, provider_name, provider_scope, provider_path,
        provider_dir, depends_on_metrics_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(run.environment.to_dict()),
                ),
            )

            execution_rows: list[tuple[object, ...]] = []
            stack: list[tuple[TestExecution, str | None]] = [
                (execution, None) for execution in run.result.executions
            ]
            while stack:
                execution, parent_id = stack.pop()
                defn = execution.definition
                spec = defn.spec
                error = execution.result.error
                error_msg = str(error) if error else None
                error_tb = self._format_traceback(error) if error else None
                test_name = spec.name
                module_path = spec.module_path
                file_path = str(module_path) if module_path else None
                class_name = spec.class_name
                suffix = spec.suffix
                tags: set[str] = set(spec.tags)
                skip_reason = spec.skip_reason
                xfail_reason = spec.xfail_reason
                case_id = spec.case_id
                execution_id = str(execution.execution_id)

                execution_rows.append(
                    (
                        execution_id,
                        run_id,
                        parent_id,
                        test_name,
                        file_path,
                        class_name,
                        str(case_id) if case_id else None,
                        suffix,
                        json.dumps(list(tags)) if tags else None,
                        skip_reason,
                        xfail_reason,
                        execution.status.value,
                        execution.duration_ms,
                        error_msg,
                        error_tb,
                    )
                )

                stack.extend(
                    (sub, execution_id) for sub in execution.sub_executions
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
        execution: TestExecution,
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
                str(metric.execution_id) if metric.execution_id else None,
                ident.name,
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
                self._to_json_list(meta.collected_from_tests),
                self._to_json_list(meta.collected_from_resources),
                self._to_json_list(meta.collected_from_cases),
                self._to_json_list(meta.collected_from_modules),
                ident.name,
                ident.scope.value
                if isinstance(ident.scope, Scope)
                else str(ident.scope),
                ident.provider_path,
                ident.provider_dir,
                self._to_json_resource_identities(metric.dependencies),
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

    def _to_json_list(self, items: set[str]) -> str | None:
        return json.dumps(list(items)) if items else None

    def _to_json_resource_identities(
        self, items: list[ResourceSpec]
    ) -> str | None:
        if not items:
            return None
        return json.dumps(
            [
                {
                    "name": item.name,
                    "scope": item.scope.value,
                    "provider_path": item.provider_path,
                    "provider_dir": item.provider_dir,
                }
                for item in items
            ]
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

    def get_metrics_for_execution(
        self, execution_id: UUID
    ) -> list[MetricResult]:
        """Get all metrics for a specific test execution."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM metrics WHERE test_execution_id = ?",
                (str(execution_id),),
            ).fetchall()
            return [self._row_to_metric(row) for row in rows]

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
        environment = RunEnvironment(
            commit_hash=env_data.get("commit_hash"),
            branch=env_data.get("branch"),
            dirty=env_data.get("dirty"),
            python_version=env_data.get("python_version", ""),
            platform=env_data.get("platform", ""),
            hostname=env_data.get("hostname", ""),
            working_directory=env_data.get("working_directory", ""),
            rue_version=env_data.get("rue_version", ""),
            env_vars=env_data.get("env_vars", {}),
        )

        exec_rows = conn.execute(
            "SELECT * FROM test_executions WHERE run_id = ?",
            (row["run_id"],),
        ).fetchall()

        executions_by_id: dict[str, TestExecution] = {}
        for exec_row in exec_rows:
            executions_by_id[exec_row["execution_id"]] = self._row_to_execution(
                exec_row
            )

        executions: list[TestExecution] = []
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

    def _row_to_execution(self, row: sqlite3.Row) -> TestExecution:
        error = (
            Exception(row["error_message"]) if row["error_message"] else None
        )
        tags_json = row["tags_json"]
        tags = set(json.loads(tags_json)) if tags_json else set()

        definition = LoadedTestDef(
            spec=TestSpec(
                locator=TestLocator(
                    module_path=Path(row["file_path"]) if row["file_path"] else Path(),
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

        return TestExecution(
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
            else Scope.PROCESS
        )

        first_at = row["first_recorded_at"]
        last_at = row["last_recorded_at"]
        identity = ResourceSpec(
            name=row["name"],
            scope=scope,
            provider_path=row["provider_path"]
            if "provider_path" in keys
            else None,
            provider_dir=row["provider_dir"]
            if "provider_dir" in keys
            else None,
        )
        metadata = MetricMetadata(
            first_item_recorded_at=datetime.fromisoformat(first_at)
            if first_at
            else None,
            last_item_recorded_at=datetime.fromisoformat(last_at)
            if last_at
            else None,
            identity=identity,
            collected_from_tests=self._from_json_set(
                row["collected_from_tests_json"]
            ),
            collected_from_resources=self._from_json_set(
                row["collected_from_resources_json"]
            ),
            collected_from_cases=self._from_json_set(
                row["collected_from_cases_json"]
            ),
            collected_from_modules=self._from_json_set(
                row["collected_from_modules_json"]
                if "collected_from_modules_json" in keys
                else None
            ),
        )

        exec_id = row["test_execution_id"]
        return MetricResult(
            metadata=metadata,
            assertion_results=[],
            value=value,
            dependencies=self._from_json_resource_identities(
                row["depends_on_metrics_json"]
                if "depends_on_metrics_json" in keys
                else None
            ),
            execution_id=UUID(exec_id) if exec_id else None,
        )

    def _from_json_set(self, json_str: str | None) -> set[str]:
        return set(json.loads(json_str)) if json_str else set()

    def _from_json_resource_identities(
        self, json_str: str | None
    ) -> list[ResourceSpec]:
        if not json_str:
            return []
        return [
            ResourceSpec(
                name=item["name"],
                scope=Scope(item["scope"]),
                provider_path=item.get("provider_path"),
                provider_dir=item.get("provider_dir"),
            )
            for item in json.loads(json_str)
        ]
