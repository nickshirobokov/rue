from pathlib import Path
from textwrap import dedent

import pytest

from rue.resources import DependencyResolver, registry
from rue.testing.models import TestStatus
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
