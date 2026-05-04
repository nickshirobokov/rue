"""Tests for Turso run storage."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import turso

from rue.assertions.base import AssertionRepr, AssertionResult
from rue.config import Config
from rue.models import Locator
from rue.predicates.models import PredicateResult
from rue.resources import ResourceSpec, Scope
from rue.resources.metrics.base import MetricMetadata, MetricResult
from rue.storage import MAX_STORED_RUNS, TursoRunRecorder, TursoRunStore
from rue.testing.models import ExecutedTest, Run, RunEnvironment, RunResult
from rue.testing.models.result import TestResult, TestStatus
from tests.helpers import make_definition


def make_environment() -> RunEnvironment:
    return RunEnvironment(
        python_version="3.12.0",
        platform="darwin",
        hostname="host",
        working_directory="/tmp/project",
        rue_version="1.0.0",
        commit_hash="abc123",
        branch="main",
        dirty=False,
    )


def test_store_initializes_strict_turso_schema(
    turso_store: TursoRunStore,
) -> None:
    with turso_store.connection() as conn:
        columns = {
            row["name"]: row["type"]
            for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        table = next(
            row
            for row in conn.execute("PRAGMA table_list").fetchall()
            if row["name"] == "runs"
        )

    assert table["strict"] == 1
    assert columns["run_id"] == "uuid"
    assert columns["start_time"] == "timestamp"
    assert columns["stopped_early"] == "boolean"
    assert columns["python_version"] == "varchar"


def test_store_rejects_invalid_native_timestamp(
    turso_store: TursoRunStore,
) -> None:
    with turso_store.connection() as conn:
        with pytest.raises(turso.DatabaseError, match="invalid timestamp"):
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, start_time, python_version, platform, hostname,
                    working_directory, rue_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "00000000-0000-0000-0000-000000000001",
                    "not-a-date",
                    "3.12.0",
                    "darwin",
                    "host",
                    "/tmp/project",
                    "1.0.0",
                ),
            )


def test_recorder_persists_normalized_run_data(database_path: Path) -> None:
    recorder = TursoRunRecorder()
    recorder.configure(Config(database_path=database_path))
    run_id = uuid4()
    execution_id = uuid4()
    case_id = uuid4()
    start_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    end_time = start_time + timedelta(minutes=5)
    definition = make_definition(
        "test_sample",
        module_path="tests/test_sample.py",
        tags={"smoke", "llm"},
        suffix="case one",
        case_id=case_id,
    )
    assertion = AssertionResult(
        expression_repr=AssertionRepr(
            expr="equals(actual, reference)",
            lines_above="actual = 'a'",
            lines_below="",
            resolved_args={"actual": "'a'", "reference": "'b'"},
        ),
        passed=False,
        error_message="predicate failed",
        predicate_results=[
            PredicateResult(
                actual="a",
                reference="b",
                name="equals",
                strict=False,
                confidence=0.25,
                value=False,
                message="db-message",
            )
        ],
    )
    execution = ExecutedTest(
        definition=definition,
        result=TestResult(
            status=TestStatus.FAILED,
            duration_ms=12.5,
            error=AssertionError("predicate failed"),
            assertion_results=[assertion],
        ),
        execution_id=execution_id,
    )
    metric = MetricResult(
        metadata=MetricMetadata(
            first_item_recorded_at=start_time,
            last_item_recorded_at=end_time,
            identity=ResourceSpec(
                locator=Locator(
                    module_path=Path("confrue.py"),
                    function_name="latency_ms",
                ),
                scope=Scope.TEST,
            ),
            consumers=[definition.spec],
            direct_providers=[
                ResourceSpec(
                    locator=Locator(
                        module_path=Path("confrue.py"),
                        function_name="model",
                    ),
                    scope=Scope.RUN,
                )
            ],
        ),
        assertion_results=[],
        value=12.5,
    )
    run = Run(
        run_id=run_id,
        start_time=start_time,
        end_time=end_time,
        environment=make_environment(),
        result=RunResult(
            executions=[execution],
            metric_results=[metric],
            total_duration_ms=15.0,
        ),
    )

    recorder.start_run(run)
    recorder.record_execution(run.run_id, execution)
    recorder.finish_run(run)
    recorder.close()

    store = TursoRunStore(database_path)
    with store.connection() as conn:
        run_row = conn.execute("SELECT * FROM runs").fetchone()
        execution_row = conn.execute("SELECT * FROM executions").fetchone()
        tags = conn.execute(
            "SELECT tag FROM execution_tags ORDER BY tag"
        ).fetchall()
        assertion_row = conn.execute("SELECT * FROM assertions").fetchone()
        predicate_row = conn.execute("SELECT * FROM predicates").fetchone()
        metric_row = conn.execute("SELECT * FROM metrics").fetchone()
        consumer_row = conn.execute(
            "SELECT * FROM metric_consumers"
        ).fetchone()
        dependency_row = conn.execute(
            "SELECT * FROM metric_dependencies"
        ).fetchone()

    assert run_row["run_id"] == str(run_id)
    assert run_row["failed"] == 1
    assert execution_row["execution_id"] == str(execution_id)
    assert execution_row["case_id"] == str(case_id)
    assert [row["tag"] for row in tags] == ["llm", "smoke"]
    assert assertion_row["expression"] == "equals(actual, reference)"
    assert assertion_row["passed"] == 0
    assert predicate_row["predicate_name"] == "equals"
    assert predicate_row["value"] == 0
    assert metric_row["name"] == "latency_ms"
    assert metric_row["value_real"] == 12.5
    assert consumer_row["kind"] == "test"
    assert dependency_row["function_name"] == "model"


def test_turso_mvcc_accepts_concurrent_non_overlapping_writes(
    turso_store: TursoRunStore,
) -> None:
    row = (
        "2024-01-01T00:00:00+00:00",
        "3.12.0",
        "darwin",
        "host",
        "/tmp/project",
        "1.0.0",
    )
    conn_one = turso_store.connect()
    conn_two = turso_store.connect()
    conn_one.execute("BEGIN CONCURRENT")
    conn_two.execute("BEGIN CONCURRENT")
    conn_one.execute(
        """
        INSERT INTO runs (
            run_id, start_time, python_version, platform, hostname,
            working_directory, rue_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("00000000-0000-0000-0000-000000000001", *row),
    )
    conn_two.execute(
        """
        INSERT INTO runs (
            run_id, start_time, python_version, platform, hostname,
            working_directory, rue_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("00000000-0000-0000-0000-000000000002", *row),
    )
    conn_one.execute("COMMIT")
    conn_two.execute("COMMIT")
    conn_one.close()
    conn_two.close()

    assert turso_store.run_count() == 2


def test_recorder_does_not_prune_old_runs(database_path: Path) -> None:
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    for index in range(MAX_STORED_RUNS + 1):
        recorder = TursoRunRecorder()
        recorder.configure(Config(database_path=database_path))
        run = Run(
            run_id=uuid4(),
            start_time=base_time + timedelta(days=index),
            environment=make_environment(),
            result=RunResult(),
        )
        recorder.start_run(run)
        recorder.finish_run(run)
        recorder.close()

    store = TursoRunStore(database_path)

    assert store.run_count() == MAX_STORED_RUNS + 1
