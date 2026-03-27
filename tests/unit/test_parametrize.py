import asyncio
from pathlib import Path

from rue.resources import registry, resource
from rue.testing import Runner
from rue.testing.decorators import parametrize
from rue.testing.models import ParameterSet, ParametrizeModifier, TestItem


def test_parametrize_invalid_inputs_are_deferred_to_execution():
    @parametrize("value", [])
    def sample(value):
        return value

    assert getattr(sample, "__rue_modifiers__", []) == []
    assert getattr(sample, "__rue_definition_error__", None) == (
        "parametrize() requires at least one value set"
    )


def test_runner_parametrize_applies_values_and_runs_all_sets(null_reporter):
    recorded = []

    def test_sample(param_a, resource_b):
        recorded.append((param_a, resource_b))

    @resource
    def resource_b():
        return "from_resource"

    modifier = ParametrizeModifier(
        parameter_sets=(
            ParameterSet(values={"param_a": "one"}, suffix="one"),
            ParameterSet(values={"param_a": "two"}, suffix="two"),
            ParameterSet(values={"param_a": "three"}, suffix="three"),
        )
    )

    item = TestItem(
        name="test_sample",
        fn=test_sample,
        module_path=Path("sample.py"),
        is_async=False,
        params=["param_a", "resource_b"],
        modifiers=[modifier],
    )

    try:
        run_result = asyncio.run(
            Runner(reporters=[null_reporter]).run(items=[item])
        )
    finally:
        registry.reset()

    execution = run_result.result.executions[0]
    assert recorded == [
        ("one", "from_resource"),
        ("two", "from_resource"),
        ("three", "from_resource"),
    ]
    assert run_result.result.passed == 1
    assert len(execution.sub_executions) == 3


def test_runner_reports_invalid_parametrize_as_error(null_reporter):
    @parametrize("value", [])
    def test_invalid(value):
        return value

    item = TestItem(
        name="test_invalid",
        fn=test_invalid,
        module_path=Path("sample.py"),
        is_async=False,
        params=["value"],
        modifiers=getattr(test_invalid, "__rue_modifiers__", []),
        definition_error=getattr(
            test_invalid, "__rue_definition_error__", None
        ),
    )

    run_result = asyncio.run(
        Runner(reporters=[null_reporter]).run(items=[item])
    )

    assert run_result.result.errors == 1
    assert "requires at least one value set" in str(
        run_result.result.executions[0].result.error
    )
