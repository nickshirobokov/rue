import builtins
from pathlib import Path
from textwrap import dedent

import pytest

from rue.resources import DependencyResolver, registry
from rue.storage import TursoSuiteRecorder, TursoSuiteStore
from rue.testing.discovery import TestLoader, TestSpecCollector
from rue.testing.execution.case import CaseFactory
from rue.testing.execution.models import TestStatus
from rue.testing.execution.suite.executable import ExecutableSuite
from tests.helpers import make_suite_context, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def _failed_executions(suite):
    failures = []
    pending = list(suite.result.test_executions)
    while pending:
        execution = pending.pop()
        if execution.result.status is not TestStatus.PASSED:
            failures.append(
                (
                    execution.definition.spec.full_name,
                    execution.result.status.value,
                    str(execution.result.error)
                    if execution.result.error
                    else None,
                )
            )
        pending.extend(execution.sub_test_executions)
    return failures


class _InvalidFactory(CaseFactory):
    async def next_case(self, loaded_test):
        _ = loaded_test
        return None


def test_case_factory_rejects_invalid_max_attempts():
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        _InvalidFactory(max_attempts=0)


async def _suite_module(
    module_path: Path,
    *,
    concurrency: int = 4,
    otel: bool = False,
):
    context = make_suite_context(
        otel=otel,
        concurrency=concurrency,
    )
    return await ExecutableSuite(
        items=materialize_tests(module_path),
        suite_execution_id=context.suite_execution_id,
        resolver=DependencyResolver(registry),
    ).execute()


@pytest.mark.asyncio
async def test_executable_suite_resolves_mixed_scope_di_graph_hooks_and_teardown(
    tmp_path: Path,
):
    module_path = tmp_path / "test_mixed_resource_graph.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend
            from rue.resources.models import Scope


            @rue.resource(scope=Scope.SUITE)
            def events():
                return ["suite"]


            @rue.resource(scope=Scope.SUITE)
            def suite_state(events):
                events.append("suite_state:setup")
                return {"cases": []}


            @rue.resource(scope=Scope.MODULE)
            def module_state(suite_state, events):
                events.append("module_state:setup")
                yield {"suite": suite_state}
                events.append(
                    f"module_state:teardown:{len(suite_state['cases'])}"
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
                case_state["module"]["suite"]["cases"].append(label)


            @rue.test.backend(ExecutionBackend.MAIN)
            @rue.test
            def test_after(suite_state, events):
                assert sorted(suite_state["cases"]) == ["left", "right"]
                assert events.count("suite_state:setup") == 1
                assert events.count("module_state:setup") == 1
                assert events.count("audit:setup") == 3
                assert events.count("case_state:setup") == 3
                assert "case_state:teardown:left" in events
                assert "case_state:teardown:right" in events
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=3)

    assert suite.result.passed == 2, _failed_executions(suite)
    assert [len(e.sub_test_executions) for e in suite.result.test_executions] == [2, 0]


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
        suitespec = TestSpecCollector((), (), None).collect_test_specs(
            (module_a_path, module_b_path)
        )
        items = TestLoader(suitespec.suite_root).load_tests(
            suitespec
        )
        context = make_suite_context(otel=False, concurrency=2)
        suite = await ExecutableSuite(
            items=items,
            suite_execution_id=context.suite_execution_id,
            resolver=DependencyResolver(registry),
        ).execute()
    finally:
        del builtins.rue_module_lifecycle_events

    assert suite.result.passed == 2, _failed_executions(suite)


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

    suite = await _suite_module(module_path, concurrency=3)

    assert suite.result.passed == 2, _failed_executions(suite)
    assert [len(e.sub_test_executions) for e in suite.result.test_executions] == [2, 2]
    assert [
        [child.result.status for child in execution.sub_test_executions]
        for execution in suite.result.test_executions
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

                async def next_case(self, loaded_test):
                    _ = loaded_test
                    value = self.next_value
                    self.next_value += 1
                    return rue.Case(inputs={"value": value})

                async def observe(self, case, execution):
                    builtins.factory_observations.append(
                        (
                            case.inputs["value"],
                            execution.result.status.value,
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
        suite = await _suite_module(module_path, concurrency=3)
    finally:
        observations = builtins.factory_observations
        seen_values = builtins.seen_case_values
        del builtins.factory_observations
        del builtins.seen_case_values

    assert suite.result.passed == 1, _failed_executions(suite)
    [execution] = suite.result.test_executions
    assert [child.result.status for child in execution.sub_test_executions] == [
        TestStatus.PASSED,
        TestStatus.PASSED,
        TestStatus.FAILED,
    ]

    factory_execution = execution.sub_test_executions[2]
    assert factory_execution.definition.spec.suffix == "generated"
    assert [
        child.definition.spec.suffix
        for child in factory_execution.sub_test_executions
    ] == ["attempt 1", "attempt 2", "attempt 3"]
    assert [
        child.result.status
        for child in factory_execution.sub_test_executions
    ] == [
        TestStatus.PASSED,
        TestStatus.FAILED,
        TestStatus.NOT_RUN,
    ]
    assert [
        child.definition.spec.case_id is not None
        for child in factory_execution.sub_test_executions
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

                async def next_case(self, loaded_test):
                    _ = loaded_test
                    if self.emitted:
                        return None
                    self.emitted = True
                    return rue.Case(inputs={"value": 7})

                async def observe(self, case, execution):
                    builtins.exhaustion_observations.append(
                        (case.inputs["value"], execution.result.status.value)
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
    recorder = TursoSuiteRecorder()
    try:
        context = make_suite_context(
            otel=False,
            concurrency=3,
            database_path=database_path,
            processors=(recorder,),
        )
        suite = await ExecutableSuite(
            items=materialize_tests(module_path),
            suite_execution_id=context.suite_execution_id,
            resolver=DependencyResolver(registry),
        ).execute()
    finally:
        observations = builtins.exhaustion_observations
        del builtins.exhaustion_observations
        recorder.close()

    assert suite.result.passed == 1, _failed_executions(suite)
    [execution] = suite.result.test_executions
    [factory_execution] = execution.sub_test_executions
    assert factory_execution.result.status is TestStatus.PASSED
    assert [
        child.result.status
        for child in factory_execution.sub_test_executions
    ] == [
        TestStatus.PASSED,
        TestStatus.NOT_RUN,
        TestStatus.NOT_RUN,
    ]
    assert observations == [(7, "passed")]

    with TursoSuiteStore(database_path).connection() as conn:
        factory_row = conn.execute(
            """
            SELECT test_execution_id FROM test_executions
            WHERE suffix = 'one generated case'
            """
        ).fetchone()
        attempt_rows = conn.execute(
            """
            SELECT suffix, status, parent_id
            FROM test_executions
            WHERE suffix LIKE 'attempt%'
            ORDER BY suffix
            """
        ).fetchall()

    assert [
        (row["suffix"], row["status"], row["parent_id"])
        for row in attempt_rows
    ] == [
        ("attempt 1", "passed", factory_row["test_execution_id"]),
        ("attempt 2", "not_run", factory_row["test_execution_id"]),
        ("attempt 3", "not_run", factory_row["test_execution_id"]),
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

                async def next_case(self, loaded_test):
                    _ = loaded_test
                    return rue.Case(inputs={"value": "subprocess"})


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            @rue.test.iterate.cases(SubprocessCase())
            @rue.test
            def test_generated_subprocess_case(case):
                assert case.inputs["value"] == "subprocess"
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=2)

    assert suite.result.passed == 1, _failed_executions(suite)
    [execution] = suite.result.test_executions
    [factory_execution] = execution.sub_test_executions
    assert factory_execution.definition.spec.suffix == "subprocess generated"
    assert [
        child.result.status
        for child in factory_execution.sub_test_executions
    ] == [
        TestStatus.PASSED,
    ]
    assert factory_execution.sub_test_executions[0].definition.spec.case_id


@pytest.mark.asyncio
async def test_metrics_sut_tracing_and_predicates_share_one_suite_context(
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

    suite = await _suite_module(module_path, concurrency=1, otel=True)

    assert suite.result.passed == 1, _failed_executions(suite)
    [metric_result] = suite.result.metric_results
    assert metric_result.metadata.identity.name == "quality"
    assert metric_result.value == 1
    assert len(metric_result.assertion_results) == 1
    [execution] = suite.result.test_executions
    assert sum(
        1
        for assertion in execution.result.assertion_results
        if assertion.predicate_results
    ) == 1
