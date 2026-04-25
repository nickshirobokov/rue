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


def test_experiment_runner_executes_four_variants_with_iterated_tests(
    tmp_path: Path,
):
    (tmp_path / "app_state.py").write_text(
        dedent(
            """
            model = "baseline"
            prompt = "baseline"
            """
        )
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
            from rue import ExecutionBackend
            from . import app_state


            @rue.test.iterate.params(
                "task,audience",
                [
                    ("refund", "support"),
                    ("pricing", "sales"),
                    ("bug", "engineering"),
                ],
                ids=[
                    "support-refund",
                    "sales-pricing",
                    "engineering-bug",
                ],
            )
            def test_local_variant_iteration(
                task,
                audience,
            ):
                model = str(app_state.model)
                prompt = str(app_state.prompt)

                assert model in ("mini", "full")
                assert prompt in ("strict", "creative")
                assert model != "baseline"
                assert prompt != "baseline"
                assert task in ("refund", "pricing", "bug")
                assert audience in ("support", "sales", "engineering")


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            @rue.test.iterate.params(
                "task,audience",
                [
                    ("refund", "support"),
                    ("pricing", "sales"),
                    ("bug", "engineering"),
                ],
                ids=[
                    "support-refund",
                    "sales-pricing",
                    "engineering-bug",
                ],
            )
            def test_subprocess_variant_iteration(
                task,
                audience,
            ):
                model = str(app_state.model)
                prompt = str(app_state.prompt)

                assert model in ("mini", "full")
                assert prompt in ("strict", "creative")
                assert model != "baseline"
                assert prompt != "baseline"
                assert prompt == "creative" or model == "full"
                assert task in ("refund", "pricing", "bug")
                assert audience in ("support", "sales", "engineering")


            @rue.test
            def test_full_model_variant_passes_direct_assertions():
                model = str(app_state.model)
                prompt = str(app_state.prompt)

                assert model == "full"
                assert prompt in ("strict", "creative")
                assert f"direct:{model}:{prompt}" in (
                    "direct:full:strict",
                    "direct:full:creative",
                )


            @rue.test
            def test_any_concrete_variant_can_read_experiment_state():
                model = str(app_state.model)
                prompt = str(app_state.prompt)
                family = {"mini": "concrete", "full": "concrete"}[model]

                assert family == "concrete"
                assert prompt in ("strict", "creative")
                assert f"state:{model}:{prompt}" in (
                    "state:mini:strict",
                    "state:mini:creative",
                    "state:full:strict",
                    "state:full:creative",
                )
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
    assert [result.passed for result in results] == [0, 2, 3, 4, 4], [
        (result.variant.label, result.failures) for result in results
    ]
    assert [result.failed for result in results] == [3, 2, 1, 0, 0]
    assert [result.errors for result in results] == [1, 0, 0, 0, 0]
