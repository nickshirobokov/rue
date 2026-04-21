import asyncio
from pathlib import Path

import pytest

from rue.testing import Runner, test as t_decorator
from rue.testing.models import IterateModifier, LoadedTestDef
from tests.unit.factories import make_definition


def test_iterate_decorator_validation():
    with pytest.raises(ValueError, match="iterate\\(\\) count must be >= 1"):

        @t_decorator.iterate(0)
        def sample1():
            pass

    with pytest.raises(
        ValueError, match="iterate\\(\\) min_passes must be >= 1"
    ):

        @t_decorator.iterate(5, min_passes=0)
        def sample2():
            pass

    with pytest.raises(
        ValueError,
        match="iterate\\(\\) min_passes .* cannot exceed count",
    ):

        @t_decorator.iterate(3, min_passes=5)
        def sample3():
            pass


def test_runner_iterate_passes_when_minimum_threshold_is_met(null_reporter):
    runner = Runner(reporters=[null_reporter])
    call_count = 0

    def test_flaky():
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            return
        raise AssertionError("flake")

    repeat_item = make_definition(
        "test_flaky",
        fn=test_flaky,
        module_path="sample.py",
        modifiers=[IterateModifier(count=5, min_passes=3)],
        tags={"iterate"},
    )

    run_result = asyncio.run(runner.run(items=[repeat_item]))
    execution = run_result.result.executions[0]
    passed = sum(
        1
        for sub in execution.sub_executions
        if sub.result.status.value == "passed"
    )

    assert run_result.result.passed == 1
    assert call_count == 5
    assert len(execution.sub_executions) == 5
    assert passed == 3


def test_runner_iterate_fails_when_threshold_is_not_met(null_reporter):
    runner = Runner(reporters=[null_reporter])
    call_count = 0

    def test_mostly_fail():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return
        raise AssertionError("fail")

    repeat_item = make_definition(
        "test_mostly_fail",
        fn=test_mostly_fail,
        module_path="sample.py",
        modifiers=[IterateModifier(count=5, min_passes=3)],
        tags={"iterate"},
    )

    run_result = asyncio.run(runner.run(items=[repeat_item]))
    execution = run_result.result.executions[0]
    passed = sum(
        1
        for sub in execution.sub_executions
        if sub.result.status.value == "passed"
    )

    assert run_result.result.failed == 1
    assert call_count == 5
    assert len(execution.sub_executions) == 5
    assert passed == 2
