import asyncio

from rue.config import Config
from rue.resources import ResourceResolver, registry, resource
from rue.testing import Runner, test as t_decorator
from rue.testing.models import ParameterSet, ParamsIterateModifier
from tests.unit.factories import make_definition


def make_runner(null_reporter) -> Runner:
    return Runner(
        config=Config.model_construct(db_enabled=False),
        reporters=[null_reporter],
    )


def test_iterate_params_invalid_inputs_are_deferred_to_execution():
    @t_decorator.iterate.params("value", [])
    def sample(value):
        return value

    assert getattr(sample, "__rue_modifiers__", []) == []
    assert getattr(sample, "__rue_definition_error__", None) == (
        "iterate.params() requires at least one value set"
    )


def test_runner_iterate_params_applies_values_and_runs_all_sets(null_reporter):
    recorded = []

    def test_sample(param_a, resource_b):
        recorded.append((param_a, resource_b))

    @resource
    def resource_b():
        return "from_resource"

    modifier = ParamsIterateModifier(
        parameter_sets=(
            ParameterSet(values={"param_a": "one"}, suffix="one"),
            ParameterSet(values={"param_a": "two"}, suffix="two"),
            ParameterSet(values={"param_a": "three"}, suffix="three"),
        ),
        min_passes=3,
    )

    item = make_definition(
        "test_sample",
        fn=test_sample,
        module_path="sample.py",
        params=["param_a", "resource_b"],
        modifiers=[modifier],
    )

    try:
        run_result = asyncio.run(
            make_runner(null_reporter).run(
                items=[item],
                resolver=ResourceResolver(registry),
            )
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


def test_runner_iterate_params_reports_invalid_definition_as_error(
    null_reporter,
):
    @t_decorator.iterate.params("value", [])
    def test_invalid(value):
        return value

    item = make_definition(
        "test_invalid",
        fn=test_invalid,
        module_path="sample.py",
        params=["value"],
        modifiers=getattr(test_invalid, "__rue_modifiers__", []),
        definition_error=getattr(
            test_invalid, "__rue_definition_error__", None
        ),
    )

    run_result = asyncio.run(
        make_runner(null_reporter).run(
            items=[item],
            resolver=ResourceResolver(registry),
        )
    )

    assert run_result.result.errors == 1
    assert "requires at least one value set" in str(
        run_result.result.executions[0].result.error
    )


def test_runner_iterate_params_uses_min_passes_threshold(null_reporter):
    recorded: list[str] = []

    def test_sample(value):
        recorded.append(value)
        if value == "three":
            raise AssertionError("boom")

    item = make_definition(
        "test_sample",
        fn=test_sample,
        module_path="sample.py",
        params=["value"],
        modifiers=[
            ParamsIterateModifier(
                parameter_sets=(
                    ParameterSet(values={"value": "one"}, suffix="one"),
                    ParameterSet(values={"value": "two"}, suffix="two"),
                    ParameterSet(values={"value": "three"}, suffix="three"),
                ),
                min_passes=2,
            )
        ],
    )

    run_result = asyncio.run(
        make_runner(null_reporter).run(
            items=[item],
            resolver=ResourceResolver(registry),
        )
    )

    assert recorded == ["one", "two", "three"]
    assert run_result.result.passed == 1


def test_iterate_params_formats_default_suffixes():
    obj = {"nested": [1, 2, 3], "enabled": True}
    long_value = "abcdefghijklmnopqrstuvwxyz1234567890"

    @t_decorator.iterate.params(
        "short,long_value,obj",
        [
            (
                "abc",
                long_value,
                obj,
            )
        ],
    )
    def sample(short, long_value, obj):
        return short, long_value, obj

    [modifier] = getattr(sample, "__rue_modifiers__")
    assert modifier.parameter_sets[0].suffix == (
        f"{{short={repr('abc')[:30]}, "
        f"long_value={repr(long_value)[:30]}, "
        f"obj={repr(obj)[:30]}}}"
    )
