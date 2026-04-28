import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from rue.assertions.base import AssertionRepr, AssertionResult
from rue.context.runtime import TestContext
from rue.models import Locator
from rue.predicates.models import PredicateResult
from rue.resources import ResourceSpec, Scope
from rue.resources.metrics.base import (
    MetricMetadata,
    MetricResult,
)
from rue.storage.sqlite import SQLiteStore
from rue.storage.sqlite.store import MAX_STORED_RUNS
from rue.testing.models.executed import ExecutedTest
from rue.testing.models.modifiers import IterateModifier
from rue.testing.models.result import TestResult, TestStatus
from rue.testing.models.run import Run, RunEnvironment, RunResult
from tests.unit.factories import make_definition, make_run_context


def make_environment(**updates) -> RunEnvironment:
    return RunEnvironment(
        python_version="3.12.0",
        platform="darwin",
        hostname="host",
        working_directory="/tmp/project",
        rue_version="1.0.0",
        **updates,
    )


def test_sqlite_store_save_and_get_run(sqlite_store: SQLiteStore) -> None:
    case_id = uuid4()
    execution_id = uuid4()
    sub_execution_id = uuid4()
    start_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    end_time = datetime(2024, 1, 1, 12, 5, tzinfo=UTC)

    definition = make_definition(
        "test_one",
        module_path="tests/test_sample.py",
        tags={"smoke"},
        suffix="{'slug': 'sample'}",
        case_id=case_id,
        modifiers=(IterateModifier(count=1, min_passes=1),),
    )
    sub_definition = make_definition(
        "test_sub", module_path="tests/test_sample.py"
    )

    sub_execution = ExecutedTest(
        definition=sub_definition,
        result=TestResult(status=TestStatus.PASSED, duration_ms=10.0),
        execution_id=sub_execution_id,
    )
    execution = ExecutedTest(
        definition=definition,
        result=TestResult(
            status=TestStatus.FAILED,
            duration_ms=20.0,
            error=Exception("boom"),
        ),
        execution_id=execution_id,
        sub_executions=[sub_execution],
    )

    metric_metadata = MetricMetadata(
        first_item_recorded_at=start_time,
        last_item_recorded_at=end_time,
        identity=ResourceSpec(
            locator=Locator(
                module_path=Path("/tmp/project/confrue_root.py"),
                function_name="latency_ms",
            ),
            scope=Scope.TEST,
        ),
        consumers=[
            definition.spec,
            ResourceSpec(
                locator=Locator(module_path=None, function_name="resource"),
                scope=Scope.RUN,
            ),
        ],
    )
    metric_result = MetricResult(
        metadata=metric_metadata,
        assertion_results=[],
        value=12.5,
        dependencies=[
            ResourceSpec(
                locator=Locator(
                    module_path=Path("/tmp/project/confrue_root.py"),
                    function_name="overall_latency",
                ),
                scope=Scope.RUN,
            )
        ],
    )

    environment = make_environment(
        commit_hash="abc123",
        branch="main",
        dirty=False,
    )

    run = Run(
        run_id=uuid4(),
        start_time=start_time,
        end_time=end_time,
        environment=environment,
        result=RunResult(
            executions=[execution],
            metric_results=[metric_result],
            total_duration_ms=123.4,
            stopped_early=False,
        ),
    )

    sqlite_store.save_run(run)
    loaded = sqlite_store.get_run(run.run_id)

    assert loaded is not None
    assert loaded.run_id == run.run_id
    assert loaded.start_time == start_time
    assert loaded.end_time == end_time
    assert loaded.environment.branch == "main"
    assert loaded.environment.commit_hash == "abc123"
    assert loaded.result.total_duration_ms == 123.4
    assert loaded.result.failed == 1
    assert loaded.result.total == 1
    assert len(loaded.result.executions) == 1
    assert loaded.result.executions[0].execution_id == execution_id
    assert (
        loaded.result.executions[0].definition.spec.suffix
        == "{'slug': 'sample'}"
    )
    assert loaded.result.executions[0].definition.spec.case_id == case_id
    assert len(loaded.result.executions[0].sub_executions) == 1
    assert (
        loaded.result.executions[0].sub_executions[0].execution_id
        == sub_execution_id
    )
    assert len(loaded.result.metric_results) == 1
    assert (
        loaded.result.metric_results[0]
        .metadata.identity.locator.function_name
        == "latency_ms"
    )
    assert loaded.result.metric_results[0].value == 12.5
    assert loaded.result.metric_results[0].metadata.identity.scope == Scope.TEST
    consumers = loaded.result.metric_results[0].metadata.consumers
    test_consumer = next(
        consumer
        for consumer in consumers
        if consumer.locator.function_name == "test_one"
    )
    assert test_consumer.locator.module_path == Path("tests/test_sample.py")
    assert test_consumer.case_id == case_id
    assert (
        loaded.result.metric_results[0].metadata.identity.locator.module_path
        == Path("/tmp/project/confrue_root.py")
    )
    assert loaded.result.metric_results[0].metadata.direct_providers == [
        ResourceSpec(
            locator=Locator(
                module_path=Path("/tmp/project/confrue_root.py"),
                function_name="overall_latency",
            ),
            scope=Scope.RUN,
        )
    ]
    assert loaded.result.metric_results[0].dependencies == [
        ResourceSpec(
            locator=Locator(
                module_path=Path("/tmp/project/confrue_root.py"),
                function_name="overall_latency",
            ),
            scope=Scope.RUN,
        )
    ]


def test_sqlite_store_list_runs(sqlite_store: SQLiteStore) -> None:
    run_one = Run(
        run_id=uuid4(),
        start_time=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 10, 10, tzinfo=UTC),
        environment=make_environment(),
        result=RunResult(),
    )
    run_two = Run(
        run_id=uuid4(),
        start_time=datetime(2024, 1, 2, 10, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 2, 10, 10, tzinfo=UTC),
        environment=make_environment(),
        result=RunResult(),
    )

    sqlite_store.save_run(run_one)
    sqlite_store.save_run(run_two)

    runs = sqlite_store.list_runs(limit=1)

    assert len(runs) == 1
    assert runs[0].run_id == run_two.run_id


def test_sqlite_store_assertions_and_predicates(
    sqlite_store: SQLiteStore,
) -> None:
    execution_id = uuid4()
    predicate_result = PredicateResult(
        actual="actual",
        reference="reference",
        name="equals",
        strict=True,
        value=False,
        confidence=0.3,
        message="nope",
    )
    definition = make_definition("test_one", module_path="tests/test_sample.py")
    make_run_context(db_enabled=False)
    with TestContext(item=definition, execution_id=execution_id):
        assertion = AssertionResult(
            expression_repr=AssertionRepr(
                expr="x == y",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
            passed=False,
            error_message="bad",
            predicate_results=[predicate_result],
        )
    execution = ExecutedTest(
        definition=definition,
        result=TestResult(
            status=TestStatus.FAILED,
            duration_ms=12.0,
            error=Exception("boom"),
            assertion_results=[assertion],
        ),
        execution_id=execution_id,
    )

    metric_metadata = MetricMetadata(
        identity=ResourceSpec(
            locator=Locator(module_path=None, function_name="count"),
            scope=Scope.RUN,
        )
    )
    with TestContext(item=definition, execution_id=execution_id):
        metric_assertion = AssertionResult(
            expression_repr=AssertionRepr(
                expr="metric > 0",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
            passed=True,
        )
    metric_result = MetricResult(
        metadata=metric_metadata,
        assertion_results=[metric_assertion],
        value=[1, 2, 3],
    )

    run = Run(
        run_id=uuid4(),
        start_time=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        environment=make_environment(),
        result=RunResult(
            executions=[execution],
            metric_results=[metric_result],
            total_duration_ms=10.0,
        ),
    )

    sqlite_store.save_run(run)

    assertions = sqlite_store.get_assertions_for_execution(execution_id)
    assert len(assertions) == 1
    assertion_repr = json.loads(assertions[0]["expression_repr"])
    assert assertion_repr["expr"] == "x == y"

    predicates = sqlite_store.get_predicates_for_assertion(assertions[0]["id"])
    assert len(predicates) == 1
    assert predicates[0]["predicate_name"] == "equals"

    run_assertions = sqlite_store.get_assertions_for_run(run.run_id)
    assert any(row["metric_id"] is not None for row in run_assertions)
    assert any(
        row["test_execution_id"] == str(execution_id) for row in run_assertions
    )
    assert any(
        json.loads(row["expression_repr"])["expr"] == "metric > 0"
        for row in run_assertions
    )


def test_sqlite_store_prunes_old_runs(sqlite_store: SQLiteStore) -> None:
    """Store should keep only MAX_STORED_RUNS most recent runs."""
    runs_to_create = MAX_STORED_RUNS + 3
    created_run_ids = []

    for i in range(runs_to_create):
        run = Run(
            run_id=uuid4(),
            start_time=datetime(2024, 1, i + 1, 10, 0, tzinfo=UTC),
            end_time=datetime(2024, 1, i + 1, 10, 10, tzinfo=UTC),
            environment=make_environment(),
            result=RunResult(),
        )
        created_run_ids.append(run.run_id)
        sqlite_store.save_run(run)

    stored_runs = sqlite_store.list_runs(limit=100)

    assert len(stored_runs) == MAX_STORED_RUNS

    stored_run_ids = {r.run_id for r in stored_runs}
    expected_run_ids = set(created_run_ids[-MAX_STORED_RUNS:])
    assert stored_run_ids == expected_run_ids
