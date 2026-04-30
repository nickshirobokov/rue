from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from uuid import uuid4

import pytest

from rue.config import Config
from rue.context.runtime import RunContext
from rue.experiments import registry as experiment_registry
from rue.experiments.models import ExperimentSpec, ExperimentVariant
from rue.experiments.runner import ExperimentRunner
from rue.models import Locator
from rue.resources import ResourceResolver, registry as resource_registry
from rue.testing.discovery import TestSpecCollector
from tests.unit.factories import make_definition


@pytest.fixture(autouse=True)
def clean_registry():
    resource_registry.reset()
    experiment_registry.reset()
    yield
    resource_registry.reset()
    experiment_registry.reset()


def test_experiment_uses_function_name_and_ids():
    @experiment_registry.experiment(["openai:gpt-5.4"], ids=["gpt"])
    def model(value):
        return value

    [definition] = experiment_registry.all()

    assert definition.locator.function_name == "model"
    assert definition.ids == ("gpt",)
    assert definition.values == ("openai:gpt-5.4",)
    assert definition.dependencies == ()
    with pytest.raises(ValueError, match="Unknown resource"):
        resource_registry.compile_graphs(
            {uuid4(): (make_definition("test_model").spec, ("model",))}
        )


def test_experiment_rejects_empty_values():
    with pytest.raises(ValueError, match="at least one value"):
        experiment_registry.experiment([])


def test_experiment_rejects_mismatched_ids():
    with pytest.raises(ValueError, match="ids"):
        experiment_registry.experiment(["a", "b"], ids=["a"])


def test_experiment_rejects_duplicate_names():
    @experiment_registry.experiment(["a"])
    def model(value):
        return value

    with pytest.raises(ValueError, match="Duplicate experiment"):

        @experiment_registry.experiment(["b"])
        def model(value):
            return value


def test_experiment_rejects_missing_value_parameter():
    with pytest.raises(ValueError, match="value parameter"):

        @experiment_registry.experiment(["a"])
        def model():
            return None


def test_experiment_variants_include_baseline_then_cartesian_product():
    variants = ExperimentVariant.build_all(
        (
            ExperimentSpec(
                locator=Locator(module_path=None, function_name="model"),
                values=("mini", "full"),
                ids=("mini", "full"),
                fn=lambda value: None,
            ),
            ExperimentSpec(
                locator=Locator(module_path=None, function_name="prompt"),
                values=("strict", "friendly"),
                ids=("strict", "friendly"),
                fn=lambda value: None,
            ),
        )
    )

    assert [variant.label for variant in variants] == [
        "baseline",
        "model=mini, prompt=strict",
        "model=mini, prompt=friendly",
        "model=full, prompt=strict",
        "model=full, prompt=friendly",
    ]


@pytest.mark.asyncio
async def test_experiment_monkeypatch_is_run_scoped():
    class Target:
        value = "baseline"

    @experiment_registry.experiment(["patched"], ids=["patched"])
    def model(value, monkeypatch):
        monkeypatch.setattr(Target, "value", value)

    [experiment] = experiment_registry.all()
    variant = ExperimentVariant.build_all((experiment,))[1]
    context = RunContext(
        config=Config.model_construct(db_enabled=False),
        run_id=uuid4(),
    )
    resolver = ResourceResolver(resource_registry)

    with context:
        await variant.apply(
            experiment_registry.all(),
            resolver=resolver,
        )
        assert Target.value == "patched"

    assert Target.value == "baseline"
    await resolver.teardown()
    assert Target.value == "baseline"


@pytest.mark.asyncio
async def test_experiment_monkeypatch_does_not_accept_method_scope():
    class Target:
        value = "baseline"

    @experiment_registry.experiment(["patched"], ids=["patched"])
    def model(value, monkeypatch):
        monkeypatch.setattr(Target, "value", value, scope="test")

    [experiment] = experiment_registry.all()
    variant = ExperimentVariant.build_all((experiment,))[1]
    context = RunContext(config=Config.model_construct(db_enabled=False))

    with context:
        with pytest.raises(TypeError, match="scope"):
            await variant.apply(
                experiment_registry.all(),
                resolver=ResourceResolver(resource_registry),
            )


def test_experiment_runner_runs_unchanged_tests_in_variant_processes(
    tmp_path: Path,
):
    (tmp_path / "app_state.py").write_text('model = "baseline"\n')
    (tmp_path / "confrue_experiment.py").write_text(
        dedent(
            """
            import rue
            from . import app_state

            @rue.experiment(["one", "two"], ids=["one", "two"])
            def model(value, monkeypatch):
                monkeypatch.setattr(app_state, "model", value)
            """
        )
    )
    module_path = tmp_path / "test_experiment_runner.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend
            from . import app_state

            IMPORTED_MODEL = app_state.model

            @rue.test
            def test_model():
                assert app_state.model == "one"

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_subprocess_imported_model():
                assert IMPORTED_MODEL == "one"
            """
        )
    )
    collection = TestSpecCollector((), (), None).build_spec_collection(
        (module_path,),
        explicit_root=tmp_path,
    )
    runner = ExperimentRunner(
        config=Config.model_construct(
            otel=False,
            db_enabled=False,
            concurrency=1,
            timeout=None,
            maxfail=None,
        )
    )
    experiments = runner.collect(collection)

    results = runner.run(collection, experiments)

    assert [result.variant.label for result in results] == [
        "baseline",
        "model=one",
        "model=two",
    ]
    assert [result.passed for result in results] == [0, 2, 0]
