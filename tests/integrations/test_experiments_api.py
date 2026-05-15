from pathlib import Path
from textwrap import dedent

import pytest

from rue.config import Config
from rue.context.runtime import SUITE_EXECUTION_CONTEXT
from rue.events import SessionEventsReceiver, SuiteEventsProcessor
from rue.experiments import registry as experiment_registry
from rue.experiments.executable import ExecutableExperiment
from rue.resources import registry
from rue.testing.discovery import TestLoader, TestSpecCollector


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    experiment_registry.reset()
    yield
    registry.reset()
    experiment_registry.reset()


class SessionCaptureProcessor(SuiteEventsProcessor):
    def __init__(self) -> None:
        self.started: list[str] = []
        self.completed: list[tuple[str, int]] = []
        self.test_executions: list[str] = []

    async def on_suite_execution_start(self, suite) -> None:
        _ = suite
        self.started.append(SUITE_EXECUTION_CONTEXT.get().experiment_variant.label)

    async def on_test_execution_complete(self, execution, suite) -> None:
        _ = suite
        spec = execution.definition.spec
        if spec.suffix is None and spec.case_id is None:
            self.test_executions.append(
                SUITE_EXECUTION_CONTEXT.get().experiment_variant.label
            )

    async def on_suite_execution_complete(self, suite) -> None:
        variant = SUITE_EXECUTION_CONTEXT.get().experiment_variant
        self.completed.append((variant.label, suite.result.total))


@pytest.mark.asyncio
async def test_executable_experiment_executes_four_variants_with_iterated_tests(
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
    suitespec = TestSpecCollector((), (), None).collect_test_specs(
        (module_path,),
        explicit_root=tmp_path,
    )
    executable_experiment = ExecutableExperiment(
        config=Config.model_construct(
            database_path=tmp_path / "rue.turso.db",
            otel=False,
            concurrency=2,
            timeout=None,
            maxfail=None,
        )
    )

    experiments = executable_experiment.collect(suitespec)
    session_processor = SessionCaptureProcessor()
    session = SessionEventsReceiver([session_processor])
    session.configure(executable_experiment.config)
    results = await executable_experiment.execute(
        suitespec,
        experiments,
        session=session,
    )
    session.close()

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
    assert session_processor.started == [
        "baseline",
        "model=mini, prompt=strict",
        "model=mini, prompt=creative",
        "model=full, prompt=strict",
        "model=full, prompt=creative",
    ]
    assert session_processor.completed == [
        ("baseline", 4),
        ("model=mini, prompt=strict", 4),
        ("model=mini, prompt=creative", 4),
        ("model=full, prompt=strict", 4),
        ("model=full, prompt=creative", 4),
    ]
    assert len(session_processor.test_executions) == 20


def test_experiment_collect_reloads_setup_after_definition_preload(
    tmp_path: Path,
):
    (tmp_path / "confrue_experiments.py").write_text(
        dedent(
            """
            import rue


            @rue.experiment(["fast", "grounded"], ids=["fast", "grounded"])
            def answer_profile(value, monkeypatch):
                monkeypatch.setattr("builtins.answer_profile", value)
            """
        )
    )
    module_path = tmp_path / "test_chatbot.py"
    module_path.write_text(
        dedent(
            """
            import rue


            @rue.test
            def test_chatbot():
                assert True
            """
        )
    )
    suitespec = TestSpecCollector((), (), None).collect_test_specs(
        (module_path,),
        explicit_root=tmp_path,
    )
    TestLoader(suitespec.suite_root).load_tests(suitespec)
    executable_experiment = ExecutableExperiment(
        config=Config.model_construct(
            database_path=tmp_path / "rue.turso.db",
            otel=False,
            concurrency=1,
            timeout=None,
            maxfail=None,
        )
    )

    experiments = executable_experiment.collect(suitespec)

    assert [experiment.name for experiment in experiments] == [
        "answer_profile"
    ]


@pytest.mark.asyncio
async def test_executable_experiment_executes_single_baseline_without_experiments(
    tmp_path: Path,
):
    module_path = tmp_path / "test_baseline.py"
    module_path.write_text(
        dedent(
            """
            import rue


            @rue.test
            def test_baseline():
                assert True
            """
        )
    )
    suitespec = TestSpecCollector((), (), None).collect_test_specs(
        (module_path,),
        explicit_root=tmp_path,
    )
    TestLoader(suitespec.suite_root).load_tests(suitespec)
    executable_experiment = ExecutableExperiment(
        config=Config.model_construct(
            database_path=tmp_path / "rue.turso.db",
            otel=False,
            concurrency=1,
            timeout=None,
            maxfail=None,
        )
    )
    session = SessionEventsReceiver([])
    session.configure(executable_experiment.config)
    results = await executable_experiment.execute(
        suitespec,
        (),
        session=session,
    )
    session.close()

    assert [result.variant.label for result in results] == ["baseline"]
    assert [result.total for result in results] == [1]
    assert [result.passed for result in results] == [1]
