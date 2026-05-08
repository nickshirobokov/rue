import builtins
from pathlib import Path
from textwrap import dedent

import pytest

from rue.resources import DependencyResolver, registry
from rue.storage import TursoRunRecorder, TursoRunStore
from rue.testing.discovery import TestLoader, TestSpecCollector
from rue.testing.models import CaseFactory, TestStatus
from rue.testing.runner import Runner
from tests.helpers import make_run_context, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def _failed_executions(run):
    failures = []
    pending = list(run.result.executions)
    while pending:
        execution = pending.pop()
        if execution.status is not TestStatus.PASSED:
            failures.append(
                (
                    execution.definition.spec.full_name,
                    execution.status.value,
                    str(execution.result.error)
                    if execution.result.error
                    else None,
                )
            )
        pending.extend(execution.sub_executions)
    return failures


class _InvalidFactory(CaseFactory):
    async def next_case(self):
        return None


def test_case_factory_rejects_invalid_max_attempts():
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        _InvalidFactory(max_attempts=0)


async def _run_module(
    module_path: Path,
    *,
    concurrency: int = 4,
    otel: bool = False,
):
    make_run_context(
        otel=otel,
        concurrency=concurrency,
    )
    return await Runner().run(
        items=materialize_tests(module_path),
        resolver=DependencyResolver(registry),
    )


@pytest.mark.asyncio
async def test_runner_resolves_mixed_scope_di_graph_hooks_and_teardown(
    tmp_path: Path,
):
    module_path = tmp_path / "test_mixed_resource_graph.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend
            from rue.resources.models import Scope


            @rue.resource(scope=Scope.RUN)
            def events():
                return ["run"]


            @rue.resource(scope=Scope.RUN)
            def run_state(events):
                events.append("run_state:setup")
                return {"cases": []}


            @rue.resource(scope=Scope.MODULE)
            def module_state(run_state, events):
                events.append("module_state:setup")
                yield {"run": run_state}
                events.append(
                    f"module_state:teardown:{len(run_state['cases'])}"
                )


            @rue.resource(scope=Scope.TEST)
            def case_state(module_state, events):
                events.append("case_state:setup")
                state = {"module": module_state, "local": []}
                yield state
                events.append(f"case_state:teardown:{state['local'][0]}")


            @rue.resource(scope=Scope.TEST, autouse=True)
            def audit(case_state, events):
                events.append("audit:setup")
                case_state["local"].append("autouse")


            @rue.test.iterate.params("label", ["left", "right"])
            @rue.test
            def test_mutates_shared_scope(label, case_state):
                case_state["local"][0] = label
                case_state["module"]["run"]["cases"].append(label)


            @rue.test.backend(ExecutionBackend.MAIN)
            @rue.test
            def test_after(run_state, events):
                assert sorted(run_state["cases"]) == ["left", "right"]
                assert events.count("run_state:setup") == 1
                assert events.count("module_state:setup") == 1
                assert events.count("audit:setup") == 3
                assert events.count("case_state:setup") == 3
                assert "case_state:teardown:left" in events
                assert "case_state:teardown:right" in events
            """
        )
    )

    run = await _run_module(module_path, concurrency=3)

    assert run.result.passed == 2, _failed_executions(run)
    assert [len(e.sub_executions) for e in run.result.executions] == [2, 0]


@pytest.mark.asyncio
async def test_module_scope_teardown_waits_for_top_level_composite(
    tmp_path: Path,
):
    module_a_path = tmp_path / "test_module_scope_a.py"
    module_b_path = tmp_path / "test_module_scope_b.py"
    module_a_path.write_text(
        dedent(
            """
            import asyncio
            import builtins

            import rue
            from rue.resources.models import Scope


            @rue.resource(scope=Scope.MODULE)
            def module_state():
                builtins.rue_module_lifecycle_events.append("setup")
                yield "ready"
                builtins.rue_module_lifecycle_events.append("teardown")


            @rue.test.iterate.params("value", [1, 2])
            @rue.test
            async def test_many(value, module_state):
                await asyncio.sleep(0)
                assert module_state == "ready"
            """
        )
    )
    module_b_path.write_text(
        dedent(
            """
            import builtins

            import rue
            from rue import ExecutionBackend


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after_module_a():
                assert builtins.rue_module_lifecycle_events == [
                    "setup",
                    "teardown",
                ]
            """
        )
    )
    builtins.rue_module_lifecycle_events = []
    try:
        collection = TestSpecCollector((), (), None).build_spec_collection(
            (module_a_path, module_b_path)
        )
        items = TestLoader(collection.suite_root).load_from_collection(
            collection
        )
        make_run_context(otel=False, concurrency=2)
        run = await Runner().run(
            items=items,
            resolver=DependencyResolver(registry),
        )
    finally:
        del builtins.rue_module_lifecycle_events

    assert run.result.passed == 2, _failed_executions(run)


@pytest.mark.asyncio
async def test_nested_iteration_rolls_up_cases_groups_and_params(
    tmp_path: Path,
):
    module_path = tmp_path / "test_iteration_contracts.py"
    module_path.write_text(
        dedent(
            """
            import rue


            cases = [
                rue.Case(inputs={"value": 1}, metadata={"name": "one"}),
                rue.Case(inputs={"value": 2}, metadata={"name": "two"}),
                rue.Case(inputs={"value": 3}, metadata={"name": "three"}),
            ]

            groups = [
                rue.CaseGroup(
                    name="low",
                    cases=cases[:2],
                    references={"limit": 2},
                    min_passes=2,
                ),
                rue.CaseGroup(
                    name="mixed",
                    cases=cases[1:],
                    references={"limit": 2},
                    min_passes=1,
                ),
            ]


            @rue.test.iterate.params(
                "bias",
                [0, 1],
                ids=["plain", "biased"],
                min_passes=1,
            )
            @rue.test.iterate.cases(cases, min_passes=2)
            @rue.test
            def test_case_thresholds(case, bias):
                assert case.inputs["value"] + bias >= 2


            @rue.test.iterate.groups(*groups, min_passes=2)
            @rue.test
            def test_group_thresholds(group, case):
                assert case.inputs["value"] <= group.references["limit"]
            """
        )
    )

    run = await _run_module(module_path, concurrency=3)

    assert run.result.passed == 2, _failed_executions(run)
    assert [len(e.sub_executions) for e in run.result.executions] == [2, 2]
    assert [
        [child.status for child in execution.sub_executions]
        for execution in run.result.executions
    ] == [
        [TestStatus.PASSED, TestStatus.PASSED],
        [TestStatus.PASSED, TestStatus.PASSED],
    ]


@pytest.mark.asyncio
async def test_case_factory_mixes_with_static_cases_and_stops_after_failure(
    tmp_path: Path,
):
    module_path = tmp_path / "test_case_factory_failure.py"
    module_path.write_text(
        dedent(
            """
            import builtins
            import rue
            from rue import ExecutionBackend


            canonical_cases = [
                rue.Case(inputs={"value": 1}, metadata={"name": "one"}),
                rue.Case(inputs={"value": 2}, metadata={"name": "two"}),
            ]


            class GeneratedCases(rue.CaseFactory):
                def __init__(self):
                    super().__init__(
                        max_attempts=3,
                        display_name="generated",
                    )
                    self.next_value = 10

                async def next_case(self):
                    value = self.next_value
                    self.next_value += 1
                    return rue.Case(inputs={"value": value})

                async def observe(self, case, execution):
                    builtins.factory_observations.append(
                        (
                            case.inputs["value"],
                            execution.status.value,
                            execution.definition.spec.case_id == case.id,
                        )
                    )


            @rue.test.backend(ExecutionBackend.MAIN)
            @rue.test.iterate.cases(
                [*canonical_cases, GeneratedCases()],
                min_passes=2,
            )
            @rue.test
            def test_static_and_generated_cases(case):
                builtins.seen_case_values.append(case.inputs["value"])
                assert case.inputs["value"] != 11
            """
        )
    )

    builtins.factory_observations = []
    builtins.seen_case_values = []
    try:
        run = await _run_module(module_path, concurrency=3)
    finally:
        observations = builtins.factory_observations
        seen_values = builtins.seen_case_values
        del builtins.factory_observations
        del builtins.seen_case_values

    assert run.result.passed == 1, _failed_executions(run)
    [execution] = run.result.executions
    assert [child.status for child in execution.sub_executions] == [
        TestStatus.PASSED,
        TestStatus.PASSED,
        TestStatus.FAILED,
    ]

    factory_execution = execution.sub_executions[2]
    assert factory_execution.definition.spec.suffix == "generated"
    assert [
        child.definition.spec.suffix
        for child in factory_execution.sub_executions
    ] == ["attempt 1", "attempt 2", "attempt 3"]
    assert [child.status for child in factory_execution.sub_executions] == [
        TestStatus.PASSED,
        TestStatus.FAILED,
        TestStatus.NOT_RUN,
    ]
    assert [
        child.definition.spec.case_id is not None
        for child in factory_execution.sub_executions
    ] == [True, True, False]
    assert observations == [
        (10, "passed", True),
        (11, "failed", True),
    ]
    assert seen_values == [1, 2, 10, 11]


@pytest.mark.asyncio
async def test_case_factory_marks_remaining_attempts_not_run_when_exhausted(
    tmp_path: Path,
):
    module_path = tmp_path / "test_case_factory_exhaustion.py"
    module_path.write_text(
        dedent(
            """
            import builtins
            import rue
            from rue import ExecutionBackend


            class OneGeneratedCase(rue.CaseFactory):
                def __init__(self):
                    super().__init__(
                        max_attempts=3,
                        display_name="one generated case",
                    )
                    self.emitted = False

                async def next_case(self):
                    if self.emitted:
                        return None
                    self.emitted = True
                    return rue.Case(inputs={"value": 7})

                async def observe(self, case, execution):
                    builtins.exhaustion_observations.append(
                        (case.inputs["value"], execution.status.value)
                    )


            @rue.test.backend(ExecutionBackend.MAIN)
            @rue.test.iterate.cases(OneGeneratedCase())
            @rue.test
            def test_generated_case(case):
                assert case.inputs["value"] == 7
            """
        )
    )

    builtins.exhaustion_observations = []
    database_path = tmp_path / "rue.turso.db"
    recorder = TursoRunRecorder()
    try:
        make_run_context(
            otel=False,
            concurrency=3,
            database_path=database_path,
            processors=(recorder,),
        )
        run = await Runner().run(
            items=materialize_tests(module_path),
            resolver=DependencyResolver(registry),
        )
    finally:
        observations = builtins.exhaustion_observations
        del builtins.exhaustion_observations
        recorder.close()

    assert run.result.passed == 1, _failed_executions(run)
    [execution] = run.result.executions
    [factory_execution] = execution.sub_executions
    assert factory_execution.status is TestStatus.PASSED
    assert [child.status for child in factory_execution.sub_executions] == [
        TestStatus.PASSED,
        TestStatus.NOT_RUN,
        TestStatus.NOT_RUN,
    ]
    assert observations == [(7, "passed")]

    with TursoRunStore(database_path).connection() as conn:
        factory_row = conn.execute(
            """
            SELECT execution_id FROM executions
            WHERE suffix = 'one generated case'
            """
        ).fetchone()
        attempt_rows = conn.execute(
            """
            SELECT suffix, status, parent_id
            FROM executions
            WHERE suffix LIKE 'attempt%'
            ORDER BY suffix
            """
        ).fetchall()

    assert [
        (row["suffix"], row["status"], row["parent_id"])
        for row in attempt_rows
    ] == [
        ("attempt 1", "passed", factory_row["execution_id"]),
        ("attempt 2", "not_run", factory_row["execution_id"]),
        ("attempt 3", "not_run", factory_row["execution_id"]),
    ]


@pytest.mark.asyncio
async def test_case_factory_runs_generated_case_with_subprocess_backend(
    tmp_path: Path,
):
    module_path = tmp_path / "test_case_factory_subprocess.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend


            class SubprocessCase(rue.CaseFactory):
                def __init__(self):
                    super().__init__(
                        max_attempts=1,
                        display_name="subprocess generated",
                    )

                async def next_case(self):
                    return rue.Case(inputs={"value": "subprocess"})


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            @rue.test.iterate.cases(SubprocessCase())
            @rue.test
            def test_generated_subprocess_case(case):
                assert case.inputs["value"] == "subprocess"
            """
        )
    )

    run = await _run_module(module_path, concurrency=2)

    assert run.result.passed == 1, _failed_executions(run)
    [execution] = run.result.executions
    [factory_execution] = execution.sub_executions
    assert factory_execution.definition.spec.suffix == "subprocess generated"
    assert [child.status for child in factory_execution.sub_executions] == [
        TestStatus.PASSED,
    ]
    assert factory_execution.sub_executions[0].definition.spec.case_id


@pytest.mark.asyncio
async def test_metrics_sut_tracing_and_predicates_share_one_run_context(
    tmp_path: Path,
):
    module_path = tmp_path / "test_traced_metrics.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue.telemetry.otel.runtime import otel_runtime


            @rue.predicate
            def has_prefix(actual: str, reference: str) -> bool:
                return actual.startswith(reference)


            class Pipeline:
                def run(self, value):
                    with otel_runtime.start_as_current_span(
                        "openai.responses.create"
                    ):
                        return f"ok:{value}"


            @rue.resource.sut
            def pipeline():
                return rue.SUT(Pipeline(), methods=["run"])


            @rue.resource.metric
            def quality():
                metric = rue.Metric()
                yield metric
                assert metric.mean == 1
                yield metric.mean


            @rue.test
            def test_pipeline(pipeline, quality):
                actual = pipeline.instance.run("alpha")
                quality.add_record(1)
                assert has_prefix(actual, "ok")
                assert {span.name for span in pipeline.root_spans} == {
                    "sut.pipeline.run",
                }
                assert {span.name for span in pipeline.llm_spans} == {
                    "openai.responses.create",
                }
            """
        )
    )

    run = await _run_module(module_path, concurrency=1, otel=True)

    assert run.result.passed == 1, _failed_executions(run)
    [metric_result] = run.result.metric_results
    assert metric_result.metadata.identity.name == "quality"
    assert metric_result.value == 1
    assert len(metric_result.assertion_results) == 1
    [execution] = run.result.executions
    assert sum(
        1
        for assertion in execution.result.assertion_results
        if assertion.predicate_results
    ) == 1
