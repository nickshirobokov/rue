from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from uuid import uuid4

import pytest

from rue.config import Config
from rue.context.runtime import CURRENT_RUN_ID, bind
from rue.experiments.models import ExperimentSpec, ExperimentVariant
from rue.experiments.runner import ExperimentRunner
from rue.experiments.runtime import apply_experiment_variant
from rue.resources import ResourceResolver, registry
from rue.testing.discovery import TestSpecCollector


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def test_experiment_uses_function_name_and_ids():
    @registry.experiment(["openai:gpt-5.4"], ids=["gpt"])
    def model(value):
        return value

    [definition] = registry.experiments()

    assert definition.experiment is not None
    assert definition.experiment.name == "model"
    assert definition.experiment.ids == ("gpt",)
    assert definition.experiment.values == ("openai:gpt-5.4",)
    assert definition.spec.name == "model"
    assert definition.spec.dependencies == ()
    assert definition.spec.sync is False


def test_experiment_rejects_empty_values():
    with pytest.raises(ValueError, match="at least one value"):
        registry.experiment([])


def test_experiment_rejects_mismatched_ids():
    with pytest.raises(ValueError, match="ids"):
        registry.experiment(["a", "b"], ids=["a"])


def test_experiment_rejects_duplicate_names():
    @registry.experiment(["a"])
    def model(value):
        return value

    with pytest.raises(ValueError, match="Duplicate experiment"):

        @registry.experiment(["b"])
        def model(value):
            return value


def test_experiment_rejects_missing_value_parameter():
    with pytest.raises(ValueError, match="value parameter"):

        @registry.experiment(["a"])
        def model():
            return None


def test_experiment_variants_include_baseline_then_cartesian_product():
    variants = ExperimentVariant.build_all(
        (
            ExperimentSpec(
                name="model",
                values=("mini", "full"),
                ids=("mini", "full"),
            ),
            ExperimentSpec(
                name="prompt",
                values=("strict", "friendly"),
                ids=("strict", "friendly"),
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

    @registry.experiment(["patched"], ids=["patched"])
    def model(value, monkeypatch):
        monkeypatch.setattr(Target, "value", value)

    [definition] = registry.experiments()
    experiment = definition.experiment
    assert experiment is not None
    variant = ExperimentVariant.build_all((experiment,))[1]
    run_id = uuid4()
    resolver = ResourceResolver(registry)

    with bind(CURRENT_RUN_ID, run_id):
        await apply_experiment_variant(
            variant,
            registry=registry,
            resolver=resolver,
            run_id=run_id,
        )
        assert Target.value == "patched"

    assert Target.value == "baseline"
    await resolver.teardown()
    assert Target.value == "baseline"


@pytest.mark.asyncio
async def test_experiment_monkeypatch_does_not_accept_method_scope():
    class Target:
        value = "baseline"

    @registry.experiment(["patched"], ids=["patched"])
    def model(value, monkeypatch):
        monkeypatch.setattr(Target, "value", value, scope="test")

    [definition] = registry.experiments()
    experiment = definition.experiment
    assert experiment is not None
    variant = ExperimentVariant.build_all((experiment,))[1]

    with bind(CURRENT_RUN_ID, uuid4()):
        with pytest.raises(TypeError, match="scope"):
            await apply_experiment_variant(
                variant,
                registry=registry,
                resolver=ResourceResolver(registry),
                run_id=uuid4(),
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
            from . import app_state

            @rue.test
            def test_model():
                assert app_state.model == "one"
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
    assert [result.passed for result in results] == [0, 1, 0]
