import asyncio
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from rich.console import Console
from tomlkit import parse
from typer.testing import CliRunner

from rue.assertions.models import AssertionRepr, AssertionResult
from rue.cli import app
from rue.cli.rendering.state import TerminalSuiteState
from rue.cli.rendering.terminal import (
    TerminalExperimentReporter,
    TerminalSuiteReporter,
)
from rue.cli.rendering.tests import TestReport
from rue.config import Config
from rue.context.models import SuiteHost
from rue.context.runtime import CURRENT_SUITE_CONTEXT
from rue.events import SuiteEventsProcessor, SuiteEventsReceiver
from rue.experiments.models import (
    ExperimentSpec,
    ExperimentVariant,
    ExperimentVariantResult,
)
from rue.models import Locator
from rue.resources import ResourceSpec, Scope
from rue.resources.metrics.models import MetricMetadata, MetricResult
from rue.storage import TursoSuiteRecorder, TursoSuiteStore
from rue.testing.discovery import TestDefinitionErrors, TestDefinitionIssue
from rue.testing.execution.suite.models import ExecutedSuite, SuiteResult
from rue.testing.execution.test.models import (
    ExecutedTest,
    LoadedTestDef,
    TestResult,
    TestStatus,
)
from rue.testing.models import SuiteSpec
from tests.helpers import make_definition, make_suite_context


runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_cli_db(tmp_path: Path, monkeypatch):
    config = Config(database_path=str(tmp_path / "rue.turso.db"))
    monkeypatch.setattr("rue.cli.run.load_config", lambda: config)
    monkeypatch.setattr(
        "rue.cli.status.command.load_config",
        lambda: config,
    )


def dummy() -> None:
    return None


def make_item(
    name: str, tags: set[str], suffix: str | None = None
) -> LoadedTestDef:
    return make_definition(
        name, fn=dummy, module_path=Path(__file__), tags=tags, suffix=suffix
    )


def make_definition_errors() -> TestDefinitionErrors:
    return TestDefinitionErrors(
        "test definition errors",
        (TestDefinitionIssue(make_item("test_bad", set()).spec, "broken"),),
    )


def raise_definition_errors(*args, **kwargs) -> None:
    del args, kwargs
    raise make_definition_errors()


def make_host(**updates) -> SuiteHost:
    return SuiteHost(
        python_version="3.12.0",
        platform="darwin",
        hostname="host",
        working_directory="/tmp/project",
        rue_version="1.0.0",
        **updates,
    )


class TestResolveProcessors:
    """Tests for processor configuration."""

    def test_default_no_processors(self):
        config = Config()
        assert config.processors == []

    def test_config_processors(self):
        config = Config(processors=["CustomProcessor"])
        assert config.processors == ["CustomProcessor"]

    def test_cli_overrides_config(self):
        config = Config(processors=["ConfiguredProcessor"])
        overridden = config.with_overrides(processors=["CustomProcessor"])
        assert overridden.processors == ["CustomProcessor"]


def test_top_level_help_lists_run_and_status():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "│ run " in result.stdout
    assert "│ status " in result.stdout
    assert "│ db " in result.stdout
    assert "│ init " in result.stdout
    assert "│ tests " not in result.stdout
    assert "│ experiments " not in result.stdout
    assert "\n│ test  " not in result.stdout


def test_root_help_does_not_expose_run_options():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--suite-execution-id" not in result.stdout


def test_run_help_exposes_all_options():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--suite-execution-id" in result.stdout
    assert "--no-db" not in result.stdout
    assert "--otel" in result.stdout
    assert "-exp" in result.stdout
    assert "--experiment" in result.stdout
    assert "--maxfail" in result.stdout
    assert "--fail-fast" in result.stdout
    assert "--concurrency" in result.stdout
    assert "--processor" in result.stdout


def test_tests_status_help_exposes_status_options():
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    assert "--database-path" in result.stdout
    assert "--keyword" in result.stdout
    assert "--suite-execution-id" not in result.stdout
    assert "--no-db" not in result.stdout


def test_cli_otel_flag_parsing():
    config = Config(otel=False)
    overridden = config.with_overrides(otel=True)
    assert overridden.otel is True


def test_cli_no_otel_flag_overrides_config():
    config = Config(otel=True)
    overridden = config.with_overrides(otel=False)
    assert overridden.otel is False


def test_cli_rejects_invalid_suite_execution_id():
    result = runner.invoke(app, ["run", "--suite-execution-id", "not-a-uuid"])
    assert result.exit_code == 2


def test_exp_with_suite_execution_id_exits_2():
    result = runner.invoke(
        app,
        ["run", "-exp", "--suite-execution-id", str(uuid4())],
    )
    assert result.exit_code == 2
    assert "--suite-execution-id" in result.stdout


def test_exp_with_maxfail_exits_2():
    result = runner.invoke(app, ["run", "-exp", "--maxfail", "3"])
    assert result.exit_code == 2
    assert "--maxfail" in result.stdout


def test_old_tests_command_is_unknown():
    result = runner.invoke(app, ["tests"])
    assert result.exit_code == 2


def test_old_experiments_command_is_unknown():
    result = runner.invoke(app, ["experiments"])
    assert result.exit_code == 2


def test_run_tests_returns_2_when_suite_execution_id_already_exists(
    database_path: Path,
    turso_store: TursoSuiteStore,
    monkeypatch,
):
    existing_suite_execution_id = uuid4()

    recorder = TursoSuiteRecorder()
    recorder.configure(Config(database_path=turso_store.path))
    asyncio.run(
        recorder.on_suite_execution_start(
            ExecutedSuite(
                suite_execution_id=existing_suite_execution_id,
                host=make_host(),
                result=SuiteResult(),
            )
        )
    )
    recorder.close()
    monkeypatch.setattr(
        "rue.cli.run.load_config",
        lambda: Config(database_path=str(database_path)),
    )

    planned = False

    def _build(self, paths, **kwargs):
        nonlocal planned
        planned = True
        return SuiteSpec(suite_root=Path.cwd())

    async def _fail_execute(self):
        del self
        msg = (
            "ExecutableSuite.execute should not be called when duplicate "
            "suite_execution_id exists"
        )
        raise AssertionError(msg)

    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs", _build
    )
    monkeypatch.setattr(
        "rue.cli.run.TestLoader.load_tests",
        lambda self, suitespec: [make_item("test_ok", set())],
    )
    monkeypatch.setattr("rue.cli.run.ExecutableSuite.execute", _fail_execute)

    result = runner.invoke(
        app,
        [
            "run",
            "--suite-execution-id",
            str(existing_suite_execution_id),
        ],
    )
    assert planned is True
    assert result.exit_code == 2


def test_run_tests_returns_2_when_definition_errors(monkeypatch):
    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs",
        lambda self, paths, **kwargs: SuiteSpec(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.run.TestLoader.load_tests",
        raise_definition_errors,
    )
    monkeypatch.setattr(
        "rue.cli.run.ExecutableSuite",
        lambda **kwargs: pytest.fail(
            "ExecutableSuite should not be constructed"
        ),
    )

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 2
    assert "Test definition errors" in result.stdout
    assert "test_bad" in result.stdout
    assert "broken" in result.stdout


def test_cli_resolves_processors_and_injects_turso_recorder(
    tmp_path, monkeypatch
):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "rue.cli.run.load_config",
        lambda: Config(
            database_path=str(tmp_path / "rue.turso.db"), otel=False
        ),
    )

    class CustomProcessor(SuiteEventsProcessor):
        pass

    custom = CustomProcessor()

    class FakeExecutableSuite:
        def __init__(self, *, items, suite_execution_id, resolver) -> None:
            context = CURRENT_SUITE_CONTEXT.get()
            captured["context"] = context
            captured["config"] = context.config
            captured["processors"] = SuiteEventsReceiver.current().processors
            captured["items"] = items
            captured["suite_execution_id"] = suite_execution_id
            captured["resolver"] = resolver

        async def execute(self):
            return ExecutedSuite()

    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs",
        lambda self, paths, **kwargs: SuiteSpec(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.run.TestLoader.load_tests",
        lambda self, suitespec: [make_item("test_ok", set())],
    )
    monkeypatch.setattr("rue.cli.run.ExecutableSuite", FakeExecutableSuite)

    result = runner.invoke(
        app,
        [
            "run",
            "--processor",
            "CustomProcessor",
            "--fail-fast",
        ],
    )

    assert result.exit_code == 0
    assert captured["config"].processors == ["CustomProcessor"]
    assert captured["config"].fail_fast is True
    assert [type(p).__name__ for p in captured["processors"]] == [
        "TerminalSuiteReporter",
        "CustomProcessor",
        "TursoSuiteRecorder",
    ]
    assert captured["processors"][1] is custom
    assert isinstance(captured["processors"][-1], TursoSuiteRecorder)
    assert captured["processors"][-1].path == tmp_path / "rue.turso.db"
    assert "TursoSuiteRecorder" not in SuiteEventsProcessor.REGISTRY


def test_terminal_suite_reporter_prints_failed_suite_and_metrics() -> None:
    make_suite_context(bind_events=False, fail_fast=False)
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=120,
    )
    reporter = TerminalSuiteReporter(console=console, verbosity=1)
    definition = make_definition(
        "test_sample",
        module_path=Path(__file__),
    )
    assertion = AssertionResult(
        expression_repr=AssertionRepr(
            expr="assert actual == expected",
            lines_above="actual = 1",
            lines_below="",
            resolved_args={"actual": "1", "expected": "2"},
        ),
        passed=False,
        error_message="not equal",
    )
    execution = ExecutedTest(
        definition=definition,
        result=TestResult(
            status=TestStatus.FAILED,
            duration_ms=5,
            error=AssertionError("not equal"),
            assertion_results=[assertion],
        ),
        test_execution_id=uuid4(),
    )
    metric = MetricResult(
        metadata=MetricMetadata(
            identity=ResourceSpec(
                locator=Locator(
                    module_path=Path(__file__),
                    function_name="latency",
                ),
                scope=Scope.TEST,
            )
        ),
        assertion_results=[assertion],
        value=20,
    )
    suite = ExecutedSuite(
        host=make_host(),
        result=SuiteResult(
            test_executions=[execution],
            metric_results=[metric],
            total_duration_ms=5,
        ),
    )

    async def drive_reporter() -> None:
        await reporter.on_collection_complete([definition], suite)
        await reporter.on_test_execution_complete(execution, suite)
        await reporter.on_suite_execution_complete(suite)

    asyncio.run(drive_reporter())

    text = output.getvalue()
    assert "ASSERTIONS" in text
    assert "Failed Assertion" in text
    assert "METRICS" in text
    assert "latency" in text
    assert "1 failed" in text


def test_terminal_suite_state_tracks_top_level_progress() -> None:
    state = TerminalSuiteState(verbosity=1)
    module_path = Path(__file__)
    top_level = make_definition(
        "test_state",
        module_path=module_path,
        collection_index=10,
    )
    child = make_definition(
        "test_state",
        module_path=module_path,
        suffix="child",
        collection_index=10,
    )
    child_execution = ExecutedTest(
        definition=child,
        result=TestResult(status=TestStatus.PASSED, duration_ms=1),
        test_execution_id=uuid4(),
    )
    failed_execution = ExecutedTest(
        definition=top_level,
        result=TestResult(status=TestStatus.FAILED, duration_ms=2),
        test_execution_id=uuid4(),
    )

    state.reset_collection([top_level])

    assert state.is_top_level_definition(top_level)
    assert not state.is_top_level_definition(child)
    assert not state.record_test_execution(child_execution)
    assert state.completed_count == 0
    assert not state.is_module_complete(module_path)

    assert state.record_test_execution(failed_execution)
    assert state.completed_count == 1
    assert state.status_counts[TestStatus.FAILED] == 1
    assert state.failures == [failed_execution]
    assert state.is_module_complete(module_path)

    state.mark_module_completed(module_path)
    assert state.all_modules_complete


def test_run_tests_keeps_normal_exit_code_when_suite_execution_id_is_unique(
    monkeypatch,
):
    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs",
        lambda self, paths, **kwargs: SuiteSpec(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.run.TestLoader.load_tests",
        lambda self, suitespec: [make_item("test_ok", set())],
    )

    result = runner.invoke(app, ["run", "--suite-execution-id", str(uuid4())])
    assert result.exit_code == 0


def test_bare_invocation_requires_command_and_shows_help():
    result = runner.invoke(app, [])

    assert result.exit_code == 2
    assert "Usage:" in result.stdout
    assert "run" in result.stdout


def test_rue_test_command_is_unknown():
    result = runner.invoke(app, ["test"])
    assert result.exit_code == 2
    assert "No such command 'test'" in result.output


@pytest.mark.parametrize(
    ("command", "status_mode"),
    [
        (["run"], False),
        (["status"], True),
    ],
    ids=["run", "status"],
)
def test_run_and_status_share_selection_parsing(
    command: list[str],
    status_mode: bool,
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, object] = {}

    def collect_test_specs(self, paths, **kwargs):
        del kwargs
        captured["paths"] = paths
        captured["include_tags"] = tuple(self.include_tags)
        captured["exclude_tags"] = tuple(self.exclude_tags)
        captured["keyword"] = self.keyword
        return SuiteSpec(suite_root=Path.cwd())

    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs",
        collect_test_specs,
    )

    if status_mode:
        monkeypatch.setattr(
            "rue.cli.status.command.TestsStatusBuilder.build",
            lambda self, suitespec: TestReport(),
        )
        monkeypatch.setattr(
            "rue.cli.status.command.TestTreeRenderer.render",
            lambda self, report, verbosity: f"status:{verbosity}",
        )
    else:
        monkeypatch.setattr(
            "rue.cli.run.TestLoader.load_tests",
            lambda self, suitespec: [make_item("test_ok", set())],
        )

        class FakeExecutableSuite:
            def __init__(self, *, items, suite_execution_id, resolver) -> None:
                del items, suite_execution_id, resolver
                captured["verbosity"] = (
                    CURRENT_SUITE_CONTEXT.get().config.verbosity
                )

            async def execute(self):
                return ExecutedSuite()

        monkeypatch.setattr("rue.cli.run.ExecutableSuite", FakeExecutableSuite)

    result = runner.invoke(
        app,
        [
            *command,
            "tests/sample",
            "-k",
            "fast and not slow",
            "-t",
            "smoke",
            "--skip-tag",
            "slow",
            "-v",
        ],
    )

    assert result.exit_code == 0
    assert captured["paths"] == ["tests/sample"]
    assert captured["include_tags"] == ("smoke",)
    assert captured["exclude_tags"] == ("slow",)
    assert captured["keyword"] == "fast and not slow"


def test_experiments_execute_shares_selection_and_preserves_db_config(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, object] = {}
    experiment_path = tmp_path / "experiments.py"
    experiment_path.write_text("")
    experiment = ExperimentSpec(
        locator=Locator(
            module_path=experiment_path,
            function_name="model",
        ),
        values=("mini",),
        ids=("mini",),
        fn=lambda value: None,
    )
    result = ExperimentVariantResult(
        variant=ExperimentVariant.build_all((experiment,))[1],
        suite_execution_id=uuid4(),
        passed=1,
        failed=0,
        errors=0,
        skipped=0,
        xfailed=0,
        xpassed=0,
        total=1,
        total_duration_ms=10,
        stopped_early=False,
    )

    def collect_test_specs(self, paths, **kwargs):
        del kwargs
        captured["paths"] = paths
        captured["include_tags"] = tuple(self.include_tags)
        captured["exclude_tags"] = tuple(self.exclude_tags)
        captured["keyword"] = self.keyword
        return SuiteSpec(suite_root=Path.cwd())

    class FakeExecutableExperiment:
        def __init__(self, *, config) -> None:
            captured["config"] = config

        def collect(self, suitespec):
            captured["suitespec"] = suitespec
            return (experiment,)

        async def execute(self, suitespec, experiments=None, *, session=None):
            captured["execute_suitespec"] = suitespec
            captured["experiments"] = experiments
            captured["session"] = session
            return (result,)

    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs",
        collect_test_specs,
    )
    monkeypatch.setattr(
        "rue.cli.run.ExecutableExperiment",
        FakeExecutableExperiment,
    )

    mutated_path = tmp_path / "mutated.py"
    mutated_path.write_text("")

    def load_tests(self, suitespec):
        suitespec.setup_chains[mutated_path] = ()
        return [make_item("test_ok", set())]

    monkeypatch.setattr(
        "rue.cli.run.TestLoader.load_tests",
        load_tests,
    )

    cli_result = runner.invoke(
        app,
        [
            "run",
            "-exp",
            str(tmp_path),
            "-k",
            "smoke",
            "-t",
            "fast",
            "--skip-tag",
            "slow",
            "-v",
        ],
    )

    assert cli_result.exit_code == 0
    assert captured["paths"] == [str(tmp_path)]
    assert captured["include_tags"] == ("fast",)
    assert captured["exclude_tags"] == ("slow",)
    assert captured["keyword"] == "smoke"
    assert captured["config"].maxfail is None
    assert captured["config"].processors == []
    assert mutated_path not in captured["suitespec"].setup_chains
    assert mutated_path not in captured["execute_suitespec"].setup_chains
    assert captured["experiments"] == (experiment,)
    assert isinstance(
        captured["session"].processors[0],
        TerminalExperimentReporter,
    )
    assert "model=mini" in cli_result.stdout


def test_experiments_execute_no_experiments_executes_baseline(monkeypatch):
    captured: dict[str, object] = {}
    result = ExperimentVariantResult(
        variant=ExperimentVariant.build_all(())[0],
        suite_execution_id=uuid4(),
        passed=1,
        failed=0,
        errors=0,
        skipped=0,
        xfailed=0,
        xpassed=0,
        total=1,
        total_duration_ms=10,
        stopped_early=False,
    )

    class FakeExecutableExperiment:
        def __init__(self, *, config) -> None:
            self.config = config

        def collect(self, suitespec):
            return ()

        async def execute(self, suitespec, experiments=None, *, session=None):
            captured["suitespec"] = suitespec
            captured["experiments"] = experiments
            captured["session"] = session
            return (result,)

    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs",
        lambda self, paths, **kwargs: SuiteSpec(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.run.ExecutableExperiment",
        FakeExecutableExperiment,
    )
    monkeypatch.setattr(
        "rue.cli.run.TestLoader.load_tests",
        lambda self, suitespec: [make_item("test_ok", set())],
    )

    cli_result = runner.invoke(app, ["run", "-exp"])

    assert cli_result.exit_code == 0
    assert captured["experiments"] == ()
    assert isinstance(
        captured["session"].processors[0],
        TerminalExperimentReporter,
    )
    assert "baseline" in cli_result.stdout


def test_experiments_execute_returns_2_when_definition_errors(monkeypatch):
    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs",
        lambda self, paths, **kwargs: SuiteSpec(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.run.TestLoader.load_tests",
        raise_definition_errors,
    )
    monkeypatch.setattr(
        "rue.cli.run.ExecutableExperiment",
        lambda **kwargs: pytest.fail(
            "ExecutableExperiment should not be constructed"
        ),
    )

    result = runner.invoke(app, ["run", "-exp"])

    assert result.exit_code == 2
    assert "Test definition errors" in result.stdout
    assert "test_bad" in result.stdout
    assert "broken" in result.stdout


def test_tests_status_returns_2_when_definition_errors(monkeypatch):
    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs",
        lambda self, paths, **kwargs: SuiteSpec(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.status.command.TestsStatusBuilder.build",
        raise_definition_errors,
    )
    result = runner.invoke(app, ["status"])

    assert result.exit_code == 2
    assert "Test definition errors" in result.stdout
    assert "test_bad" in result.stdout
    assert "broken" in result.stdout


def test_tests_status_does_not_create_missing_db(tmp_path, monkeypatch):
    missing_db = tmp_path / "missing.db"

    monkeypatch.setattr(
        "rue.cli.options.TestSpecCollector.collect_test_specs",
        lambda self, paths, **kwargs: SuiteSpec(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.status.command.TestsStatusBuilder.build",
        lambda self, suitespec: TestReport(),
    )
    monkeypatch.setattr(
        "rue.cli.status.command.TestTreeRenderer.render",
        lambda self, report, verbosity: "status",
    )

    result = runner.invoke(
        app,
        ["status", "--database-path", str(missing_db)],
    )

    assert result.exit_code == 0
    assert not missing_db.exists()


def test_rue_init_writes_pytest_entrypoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n')
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    doc = parse(pyproject.read_text())
    rue_ep = doc["project"]["entry-points"]["pytest11"]["rue"]
    assert rue_ep == "rue.pytest_plugin"


def test_rue_init_fails_without_pyproject(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 1


def test_rue_init_second_invocation_reports_already_installed(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n')
    assert runner.invoke(app, ["init"]).exit_code == 0
    text_after_first = pyproject.read_text()
    second = runner.invoke(app, ["init"])
    assert second.exit_code == 0
    assert "already installed" in second.stdout.lower()
    assert pyproject.read_text() == text_after_first
