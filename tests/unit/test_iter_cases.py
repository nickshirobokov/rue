import asyncio
from pathlib import Path
from typing import Any

import pytest

from rue.testing import Runner, test
from rue.testing.models import (
    Case,
    CaseGroup,
    CasesIterateModifier,
    GroupsIterateModifier,
    TestItem,
)


def test_iterate_cases_decorator_rejects_invalid_threshold():
    cases = [Case(inputs={"x": 1}), Case(inputs={"x": 2})]

    with pytest.raises(
        ValueError,
        match="iterate\\.cases\\(\\) min_passes .* cannot exceed count",
    ):

        @test.iterate.cases(*cases, min_passes=3)
        def my_test(case):
            pass


def test_iterate_cases_empty_is_deferred_to_execution():
    @test.iterate.cases()
    def my_test(case):
        pass

    assert getattr(my_test, "__rue_modifiers__", []) == []
    assert getattr(my_test, "__rue_definition_error__", None) == (
        "iterate.cases() requires at least one case"
    )


def test_runner_iterate_cases_preserves_case_identity_and_metadata(null_reporter):
    seen_cases: list[Case[Any, Any]] = []
    cases = [
        Case(inputs={"x": 1}, metadata={"slug": "one"}),
        Case(inputs={"x": 2}, metadata={"slug": "two"}),
    ]

    def test_collect_case(case):
        seen_cases.append(case)

    item = TestItem(
        name="test_collect_case",
        fn=test_collect_case,
        module_path=Path("sample.py"),
        is_async=False,
        params=["case"],
        modifiers=[CasesIterateModifier(cases=tuple(cases), min_passes=2)],
    )

    run_result = asyncio.run(
        Runner(reporters=[null_reporter]).run(items=[item])
    )
    execution = run_result.result.executions[0]

    assert run_result.result.passed == 1
    assert seen_cases == cases
    assert [sub.definition.suffix for sub in execution.sub_executions] == [
        repr(case.metadata) for case in cases
    ]
    assert [sub.definition.case_id for sub in execution.sub_executions] == [
        case.id for case in cases
    ]


def test_runner_iterate_cases_passes_when_threshold_is_met(null_reporter):
    cases = [Case(inputs={"x": i}) for i in range(1, 6)]

    def test_partial_pass(case):
        if case.inputs["x"] >= 4:
            raise AssertionError("fail")

    item = TestItem(
        name="test_partial_pass",
        fn=test_partial_pass,
        module_path=Path("sample.py"),
        is_async=False,
        params=["case"],
        modifiers=[CasesIterateModifier(cases=tuple(cases), min_passes=3)],
    )

    run_result = asyncio.run(
        Runner(reporters=[null_reporter]).run(items=[item])
    )
    execution = run_result.result.executions[0]
    passed = sum(
        1
        for sub in execution.sub_executions
        if sub.result.status.value == "passed"
    )

    assert run_result.result.passed == 1
    assert len(execution.sub_executions) == 5
    assert passed == 3
    assert execution.result.status.value == "passed"


def test_runner_iterate_cases_fails_when_threshold_is_not_met(null_reporter):
    cases = [Case(inputs={"x": i}) for i in range(1, 6)]

    def test_mostly_fail(case):
        if case.inputs["x"] > 2:
            raise AssertionError("fail")

    item = TestItem(
        name="test_mostly_fail",
        fn=test_mostly_fail,
        module_path=Path("sample.py"),
        is_async=False,
        params=["case"],
        modifiers=[CasesIterateModifier(cases=tuple(cases), min_passes=3)],
    )

    run_result = asyncio.run(
        Runner(reporters=[null_reporter]).run(items=[item])
    )
    execution = run_result.result.executions[0]
    passed = sum(
        1
        for sub in execution.sub_executions
        if sub.result.status.value == "passed"
    )

    assert run_result.result.failed == 1
    assert len(execution.sub_executions) == 5
    assert passed == 2
    assert execution.result.status.value == "failed"


def test_iterate_groups_empty_is_deferred_to_execution():
    @test.iterate.groups()
    def my_test(group, case):
        pass

    assert getattr(my_test, "__rue_modifiers__", []) == []
    assert getattr(my_test, "__rue_definition_error__", None) == (
        "iterate.groups() requires at least one case group"
    )


def test_runner_iterate_groups_injects_group_and_case_and_nests(
    null_reporter,
):
    g1_cases = [Case(inputs={"x": 1}), Case(inputs={"x": 2})]
    g2_cases = [Case(inputs={"x": 3})]
    groups = [
        CaseGroup(name="alpha", cases=g1_cases, min_passes=1),
        CaseGroup(name="beta", cases=g2_cases, min_passes=1),
    ]
    seen_pairs: list[tuple[str, Any]] = []

    def test_collect_group_case(group, case):
        seen_pairs.append((group.name, case.id))

    item = TestItem(
        name="test_collect_group_case",
        fn=test_collect_group_case,
        module_path=Path("sample.py"),
        is_async=False,
        params=["group", "case"],
        modifiers=[GroupsIterateModifier(groups=tuple(groups), min_passes=2)],
    )

    run_result = asyncio.run(
        Runner(reporters=[null_reporter]).run(items=[item])
    )
    execution = run_result.result.executions[0]

    assert run_result.result.passed == 1
    assert len(seen_pairs) == 3
    assert [sub.definition.suffix for sub in execution.sub_executions] == [
        "alpha",
        "beta",
    ]
    assert len(execution.sub_executions[0].sub_executions) == 2
    assert len(execution.sub_executions[1].sub_executions) == 1


def test_runner_iterate_groups_uses_group_and_outer_min_passes(
    null_reporter,
):
    groups = [
        CaseGroup(
            name="alpha",
            cases=[
                Case(inputs={"x": 1}),
                Case(inputs={"x": 2}),
                Case(inputs={"x": 3}),
            ],
            min_passes=2,
        ),
        CaseGroup(
            name="beta",
            cases=[Case(inputs={"x": 1}), Case(inputs={"x": 2})],
            min_passes=2,
        ),
    ]

    def test_group_threshold(group, case):
        if group.name == "alpha" and case.inputs["x"] == 3:
            raise AssertionError("alpha fail")
        if group.name == "beta" and case.inputs["x"] == 2:
            raise AssertionError("beta fail")

    item = TestItem(
        name="test_group_threshold",
        fn=test_group_threshold,
        module_path=Path("sample.py"),
        is_async=False,
        params=["group", "case"],
        modifiers=[GroupsIterateModifier(groups=tuple(groups), min_passes=1)],
    )

    run_result = asyncio.run(
        Runner(reporters=[null_reporter]).run(items=[item])
    )
    execution = run_result.result.executions[0]
    group_statuses = [
        sub.result.status.value for sub in execution.sub_executions
    ]

    assert run_result.result.passed == 1
    assert execution.result.status.value == "passed"
    assert group_statuses == ["passed", "failed"]


def test_iterate_groups_decorator_rejects_invalid_threshold():
    groups = [
        CaseGroup(name="alpha", cases=[Case(inputs={"x": 1})], min_passes=1),
        CaseGroup(name="beta", cases=[Case(inputs={"x": 2})], min_passes=1),
    ]

    with pytest.raises(
        ValueError,
        match="iterate\\.groups\\(\\) min_passes .* cannot exceed count",
    ):

        @test.iterate.groups(*groups, min_passes=3)
        def my_test(group, case):
            pass
