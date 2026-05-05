from pathlib import Path
from uuid import uuid4

import pytest
from tomlkit import parse
from typer.testing import CliRunner

from rue.cli import app
from rue.cli.tests.status import TestsStatusReport
from rue.config import Config
from rue.context.runtime import CURRENT_RUN_CONTEXT
from rue.events import RunEventsProcessor, RunEventsReceiver
from rue.experiments.models import (
    ExperimentSpec,
    ExperimentVariant,
    ExperimentVariantResult,
)
from rue.models import Locator
from rue.storage import TursoRunRecorder, TursoRunStore
from rue.testing import LoadedTestDef
from rue.testing.discovery import TestDefinitionErrors, TestDefinitionIssue
from rue.context.models import RunEnvironment
from rue.testing.models.run import ExecutedRun, RunResult
from rue.testing.models.spec import TestSpecCollection
from tests.helpers import make_definition


runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_cli_db(tmp_path: Path, monkeypatch):
    config = Config(database_path=str(tmp_path / "rue.turso.db"))
    monkeypatch.setattr("rue.cli.tests.run.load_config", lambda: config)
    monkeypatch.setattr(
        "rue.cli.tests.status.command.load_config",
        lambda: config,
    )
    monkeypatch.setattr("rue.cli.experiments.run.load_config", lambda: config)


def dummy() -> None:
    return None


def make_item(
    name: str, tags: set[str], suffix: str | None = None
) -> LoadedTestDef:
    return make_definition(
        name, fn=dummy, module_path="module.py", tags=tags, suffix=suffix
    )


def make_definition_errors() -> TestDefinitionErrors:
    return TestDefinitionErrors(
        "test definition errors",
        (TestDefinitionIssue(make_item("test_bad", set()).spec, "broken"),),
    )


def raise_definition_errors(*args, **kwargs) -> None:
    del args, kwargs
    raise make_definition_errors()


def make_environment(**updates) -> RunEnvironment:
    return RunEnvironment(
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
        config = Config(processors=["ConsoleReporter"])
        assert config.processors == ["ConsoleReporter"]

    def test_cli_overrides_config(self):
        config = Config(processors=["OtelReporter"])
        overridden = config.with_overrides(processors=["ConsoleReporter"])
        assert overridden.processors == ["ConsoleReporter"]


def test_top_level_help_lists_tests_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "│ tests " in result.stdout
    assert "│ experiments " in result.stdout
    assert "\n│ test  " not in result.stdout


def test_tests_group_help_does_not_invoke_run_help():
    result = runner.invoke(app, ["tests", "--help"])
    assert result.exit_code == 0
    assert "Usage: rue tests [OPTIONS] COMMAND [ARGS]..." in result.stdout
    assert "--run-id" not in result.stdout


def test_tests_run_help_exposes_run_options():
    result = runner.invoke(app, ["tests", "run", "--help"])
    assert result.exit_code == 0
    assert "--run-id" in result.stdout
    assert "--no-db" not in result.stdout
    assert "--db-path" not in result.stdout
    assert "--otel" in result.stdout


def test_experiments_run_help_exposes_experiment_options():
    result = runner.invoke(app, ["experiments", "run", "--help"])
    assert result.exit_code == 0
    assert "--concurrency" in result.stdout
    assert "--timeout" in result.stdout
    assert "--run-id" not in result.stdout
    assert "--db-path" not in result.stdout


def test_tests_status_help_exposes_status_options():
    result = runner.invoke(app, ["tests", "status", "--help"])
    assert result.exit_code == 0
    assert "--database-path" in result.stdout
    assert "--keyword" in result.stdout
    assert "--run-id" not in result.stdout
    assert "--no-db" not in result.stdout


def test_cli_otel_flag_parsing():
    config = Config(otel=False)
    overridden = config.with_overrides(otel=True)
    assert overridden.otel is True


def test_cli_no_otel_flag_overrides_config():
    config = Config(otel=True)
    overridden = config.with_overrides(otel=False)
    assert overridden.otel is False


def test_cli_rejects_invalid_run_id():
    result = runner.invoke(app, ["tests", "run", "--run-id", "not-a-uuid"])
    assert result.exit_code == 2


@pytest.mark.parametrize(
    "command",
    [["tests"], ["tests", "run"]],
    ids=["alias", "run"],
)
def test_run_tests_returns_2_when_run_id_already_exists(
    command: list[str],
    database_path: Path,
    turso_store: TursoRunStore,
    monkeypatch,
):
    existing_run_id = uuid4()

    recorder = TursoRunRecorder()
    recorder.configure(Config(database_path=turso_store.path))
    recorder.start_run(
        ExecutedRun(
            run_id=existing_run_id,
            environment=make_environment(),
            result=RunResult(),
        )
    )
    recorder.close()
    monkeypatch.setattr(
        "rue.cli.tests.run.load_config",
        lambda: Config(database_path=str(database_path)),
    )

    planned = False

    def _build(self, paths, **kwargs):
        nonlocal planned
        planned = True
        return TestSpecCollection(suite_root=Path.cwd())

    async def _fail_run(self, items=None, path=None):
        del self, items, path
        msg = "Runner.run should not be called when duplicate run_id exists"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection", _build
    )
    monkeypatch.setattr(
        "rue.cli.tests.run.TestLoader.load_from_collection",
        lambda self, collection: [make_item("test_ok", set())],
    )
    monkeypatch.setattr("rue.cli.tests.run.Runner.run", _fail_run)

    result = runner.invoke(
        app,
        [
            *command,
            "--run-id",
            str(existing_run_id),
        ],
    )
    assert planned is True
    assert result.exit_code == 2


@pytest.mark.parametrize(
    "command",
    [["tests"], ["tests", "run"]],
    ids=["alias", "run"],
)
def test_run_tests_returns_2_when_definition_errors(
    command: list[str], monkeypatch
):
    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.tests.run.TestLoader.load_from_collection",
        raise_definition_errors,
    )
    monkeypatch.setattr(
        "rue.cli.tests.run.Runner",
        lambda **kwargs: pytest.fail("Runner should not be constructed"),
    )

    result = runner.invoke(app, [*command])

    assert result.exit_code == 2
    assert "Test definition errors" in result.stdout
    assert "test_bad" in result.stdout
    assert "broken" in result.stdout


def test_cli_resolves_processors_and_injects_turso_recorder(
    tmp_path, monkeypatch
):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "rue.cli.tests.run.load_config",
        lambda: Config(
            database_path=str(tmp_path / "rue.turso.db"), otel=False
        ),
    )

    class CustomProcessor(RunEventsProcessor):
        pass

    custom = CustomProcessor()

    class FakeRunner:
        def __init__(
            self,
            *,
            capture_output=True,
        ) -> None:
            context = CURRENT_RUN_CONTEXT.get()
            captured["context"] = context
            captured["config"] = context.config
            captured["processors"] = RunEventsReceiver.current().processors
            captured["capture_output"] = capture_output

        async def run(self, items, *, resolver):
            captured["items"] = items
            captured["resolver"] = resolver
            return ExecutedRun()

    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.tests.run.TestLoader.load_from_collection",
        lambda self, collection: [make_item("test_ok", set())],
    )
    monkeypatch.setattr("rue.cli.tests.run.Runner", FakeRunner)

    result = runner.invoke(
        app,
        [
            "tests",
            "run",
            "--processor",
            "CustomProcessor",
            "--fail-fast",
            "--show-output",
        ],
    )

    assert result.exit_code == 0
    assert captured["config"].processors == ["CustomProcessor"]
    assert captured["config"].fail_fast is True
    assert [type(p).__name__ for p in captured["processors"]] == [
        "ConsoleReporter",
        "CustomProcessor",
        "TursoRunRecorder",
    ]
    assert captured["processors"][1] is custom
    assert isinstance(captured["processors"][-1], TursoRunRecorder)
    assert captured["processors"][-1].path == tmp_path / "rue.turso.db"
    assert "TursoRunRecorder" not in RunEventsProcessor.REGISTRY
    assert captured["capture_output"] is False


@pytest.mark.parametrize(
    "command",
    [["tests"], ["tests", "run"]],
    ids=["alias", "run"],
)
def test_run_tests_keeps_normal_exit_code_when_run_id_is_unique(
    command: list[str], monkeypatch
):
    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.tests.run.TestLoader.load_from_collection",
        lambda self, collection: [make_item("test_ok", set())],
    )

    result = runner.invoke(app, [*command, "--run-id", str(uuid4())])
    assert result.exit_code == 0


def test_tests_without_subcommand_defaults_to_run(tmp_path: Path, monkeypatch):
    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(
            self,
            *,
            capture_output=True,
        ) -> None:
            context = CURRENT_RUN_CONTEXT.get()
            captured["context"] = context
            captured["config"] = context.config
            captured["capture_output"] = capture_output

        async def run(self, items, *, resolver):
            captured["items"] = items
            captured["resolver"] = resolver
            return ExecutedRun()

    def build_spec_collection(self, paths, **kwargs):
        del self, kwargs
        captured["paths"] = paths
        return TestSpecCollection(suite_root=Path.cwd())

    monkeypatch.setattr(
        "rue.cli.tests.run.load_config",
        lambda: Config(
            database_path=str(tmp_path / "rue.turso.db"), fail_fast=True
        ),
    )
    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        build_spec_collection,
    )
    monkeypatch.setattr(
        "rue.cli.tests.run.TestLoader.load_from_collection",
        lambda self, collection: [make_item("test_ok", set())],
    )
    monkeypatch.setattr("rue.cli.tests.run.Runner", FakeRunner)

    result = runner.invoke(app, ["tests"])

    assert result.exit_code == 0
    assert captured["paths"] == ["."]
    assert captured["config"].fail_fast is True


def test_rue_test_command_is_unknown():
    result = runner.invoke(app, ["test"])
    assert result.exit_code == 2
    assert "No such command 'test'" in result.output


@pytest.mark.parametrize(
    ("command", "status_mode"),
    [
        (["tests", "run"], False),
        (["tests", "status"], True),
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

    def build_spec_collection(self, paths, **kwargs):
        del kwargs
        captured["paths"] = paths
        captured["include_tags"] = tuple(self.include_tags)
        captured["exclude_tags"] = tuple(self.exclude_tags)
        captured["keyword"] = self.keyword
        return TestSpecCollection(suite_root=Path.cwd())

    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        build_spec_collection,
    )

    if status_mode:
        monkeypatch.setattr(
            "rue.cli.tests.status.command.TestsStatusBuilder.build",
            lambda self, collection, store=None: TestsStatusReport(),
        )
        monkeypatch.setattr(
            "rue.cli.tests.status.command.status_renderer.render",
            lambda report, verbosity: f"status:{verbosity}",
        )
    else:
        monkeypatch.setattr(
            "rue.cli.tests.run.TestLoader.load_from_collection",
            lambda self, collection: [make_item("test_ok", set())],
        )

        class FakeRunner:
            def __init__(self, **kwargs) -> None:
                del kwargs
                captured["verbosity"] = (
                    CURRENT_RUN_CONTEXT.get().config.verbosity
                )

            async def run(self, items, *, resolver):
                del items, resolver
                return ExecutedRun()

        monkeypatch.setattr("rue.cli.tests.run.Runner", FakeRunner)

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


def test_experiments_run_shares_selection_and_preserves_db_config(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, object] = {}
    experiment = ExperimentSpec(
        locator=Locator(module_path=None, function_name="model"),
        values=("mini",),
        ids=("mini",),
        fn=lambda value: None,
    )
    result = ExperimentVariantResult(
        variant=ExperimentVariant.build_all((experiment,))[1],
        run_id=uuid4(),
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

    def build_spec_collection(self, paths, **kwargs):
        del kwargs
        captured["paths"] = paths
        captured["include_tags"] = tuple(self.include_tags)
        captured["exclude_tags"] = tuple(self.exclude_tags)
        captured["keyword"] = self.keyword
        return TestSpecCollection(suite_root=Path.cwd())

    class FakeExperimentRunner:
        def __init__(self, *, config) -> None:
            captured["config"] = config

        def collect(self, collection):
            captured["collection"] = collection
            return (experiment,)

        def run(self, collection, experiments=None):
            captured["run_collection"] = collection
            captured["experiments"] = experiments
            return (result,)

    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        build_spec_collection,
    )
    monkeypatch.setattr(
        "rue.cli.experiments.run.ExperimentRunner",
        FakeExperimentRunner,
    )

    cli_result = runner.invoke(
        app,
        [
            "experiments",
            "run",
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
    assert captured["experiments"] == (experiment,)
    assert "model=mini" in cli_result.stdout


def test_experiments_run_no_experiments_does_not_run(monkeypatch):
    class FakeExperimentRunner:
        def __init__(self, *, config) -> None:
            self.config = config

        def collect(self, collection):
            return ()

        def run(self, collection, experiments=None):
            raise AssertionError("ExperimentRunner.run should not be called")

    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.experiments.run.ExperimentRunner",
        FakeExperimentRunner,
    )

    result = runner.invoke(app, ["experiments", "run"])

    assert result.exit_code == 0
    assert "No experiments found" in result.stdout


def test_experiments_run_returns_2_when_definition_errors(monkeypatch):
    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.experiments.run.TestLoader.load_from_collection",
        raise_definition_errors,
    )
    monkeypatch.setattr(
        "rue.cli.experiments.run.ExperimentRunner",
        lambda **kwargs: pytest.fail(
            "ExperimentRunner should not be constructed"
        ),
    )

    result = runner.invoke(app, ["experiments", "run"])

    assert result.exit_code == 2
    assert "Test definition errors" in result.stdout
    assert "test_bad" in result.stdout
    assert "broken" in result.stdout


def test_tests_status_returns_2_when_definition_errors(monkeypatch):
    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.tests.status.command.TestsStatusBuilder.build",
        raise_definition_errors,
    )
    monkeypatch.setattr(
        "rue.cli.tests.status.command.status_renderer.render",
        lambda report, verbosity: pytest.fail("status should not render"),
    )

    result = runner.invoke(app, ["tests", "status"])

    assert result.exit_code == 2
    assert "Test definition errors" in result.stdout
    assert "test_bad" in result.stdout
    assert "broken" in result.stdout


def test_tests_status_does_not_create_missing_db(tmp_path, monkeypatch):
    missing_db = tmp_path / "missing.db"

    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.tests.status.command.TestsStatusBuilder.build",
        lambda self, collection, store=None: TestsStatusReport(),
    )
    monkeypatch.setattr(
        "rue.cli.tests.status.command.status_renderer.render",
        lambda report, verbosity: "status",
    )

    result = runner.invoke(
        app,
        ["tests", "status", "--database-path", str(missing_db)],
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
