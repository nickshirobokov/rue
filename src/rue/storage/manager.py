"""SQLite database manager for Rue test runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from rue.models import Locator, Spec
from rue.resources import ResourceSpec, Scope
from rue.resources.metrics.base import (
    CalculatedValue,
    MetricMetadata,
    MetricResult,
)
from rue.storage.sqlite.migrations import MigrationError, MigrationRunner
from rue.storage.sqlite.migrations.runner import Migration
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


MAX_STORED_RUNS = 5


class DBManager:
    """SQLite-backed database manager for Rue test runs."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(".rue/rue.db") if path is None else Path(path)

    def initialize(self) -> None:
        """Create or migrate the database to the current schema."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def get_current_version(self) -> int:
        """Return the current SQLite schema version."""
        return MigrationRunner(self.path).get_current_version()

    def get_target_version(self) -> int:
        """Return the target SQLite schema version."""
        return MigrationRunner(self.path).get_target_version()

    def get_pending_migrations(self) -> list[Migration]:
        """Return pending SQLite migrations."""
        return MigrationRunner(self.path).get_pending_migrations()

    def needs_migration(self) -> bool:
        """Return whether the SQLite schema is behind code."""
        return MigrationRunner(self.path).needs_migration()

    def can_migrate(self) -> bool:
        """Return whether pending migrations can be applied."""
        return MigrationRunner(self.path).can_migrate()

    def migrate(self) -> None:
        """Apply pending migrations."""
        MigrationRunner(self.path).migrate()

    def reset(self) -> None:
        """Delete and recreate the database."""
        if self.path.exists():
            self.path.unlink()
        for suffix in ("-wal", "-shm"):
            companion = self.path.with_name(self.path.name + suffix)
            if companion.exists():
                companion.unlink()
        self.initialize()

    def backup(self, backup_path: Path) -> None:
        """Write a SQLite backup to the given path."""
        with (
            sqlite3.connect(self.path) as source,
            sqlite3.connect(backup_path) as dest,
        ):
            source.backup(dest)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def run_exists(self, run_id: UUID) -> bool:
        """Return whether a run id already exists."""
        if not self.path.exists():
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM runs WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
            return row is not None

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
        provider_path = (
            row["provider_path"] if "provider_path" in keys else None
        )
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
