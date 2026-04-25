from pathlib import Path
from textwrap import dedent

import pytest

from rue.config import Config
from rue.experiments.runner import ExperimentRunner
from rue.resources import registry
from rue.testing.discovery import TestSpecCollector


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def test_experiment_runner_executes_four_cartesian_variants(
    tmp_path: Path,
):
    (tmp_path / "app_state.py").write_text(
        'model = "baseline"\nprompt = "baseline"\n'
    )
    (tmp_path / "confrue_experiments.py").write_text(
        dedent(
            """
            import rue
            from . import app_state


            @rue.experiment(["mini", "full"], ids=["mini", "full"])
            def model(value, monkeypatch):
                monkeypatch.setattr(app_state, "model", value)


            @rue.experiment(["strict", "creative"], ids=["strict", "creative"])
            def prompt(value, monkeypatch):
                monkeypatch.setattr(app_state, "prompt", value)
            """
        )
    )
    module_path = tmp_path / "test_experiment_variants.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from . import app_state


            @rue.test
            def test_mini_strict():
                assert (
                    app_state.model,
                    app_state.prompt,
                ) == ("mini", "strict")


            @rue.test
            def test_mini_creative():
                assert (
                    app_state.model,
                    app_state.prompt,
                ) == ("mini", "creative")


            @rue.test
            def test_full_strict():
                assert (
                    app_state.model,
                    app_state.prompt,
                ) == ("full", "strict")


            @rue.test
            def test_full_creative():
                assert (
                    app_state.model,
                    app_state.prompt,
                ) == ("full", "creative")
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
            concurrency=2,
            timeout=None,
            maxfail=None,
        )
    )

    experiments = runner.collect(collection)
    results = runner.run(collection, experiments)

    assert [experiment.name for experiment in experiments] == [
        "model",
        "prompt",
    ]
    assert [result.variant.label for result in results] == [
        "baseline",
        "model=mini, prompt=strict",
        "model=mini, prompt=creative",
        "model=full, prompt=strict",
        "model=full, prompt=creative",
    ]
    assert [result.total for result in results] == [4, 4, 4, 4, 4]
    assert [result.passed for result in results] == [0, 1, 1, 1, 1]
    assert [result.failed for result in results] == [4, 3, 3, 3, 3]
    assert [result.errors for result in results] == [0, 0, 0, 0, 0]
