from pathlib import Path
from uuid import uuid4

import pytest
from tomlkit import parse
from typer.testing import CliRunner

from rue.cli import app
from rue.cli.tests.status import TestsStatusReport
from rue.config import Config
from rue.storage.sqlite import SQLiteStore
from rue.testing import LoadedTestDef
from rue.testing.models.spec import TestSpecCollection
from rue.testing.models.run import Run, RunEnvironment, RunResult
from tests.unit.factories import make_definition


runner = CliRunner()


def dummy() -> None:
    return None


def make_item(
    name: str, tags: set[str], suffix: str | None = None
) -> LoadedTestDef:
    return make_definition(
        name, fn=dummy, module_path="module.py", tags=tags, suffix=suffix
    )


def make_environment(**updates) -> RunEnvironment:
    return RunEnvironment(
        python_version="3.12.0",
        platform="darwin",
        hostname="host",
        working_directory="/tmp/project",
        rue_version="1.0.0",
        **updates,
    )


class TestResolveReporters:
    """Tests for reporter resolution via CLI and Config."""

    def test_default_no_reporters(self):
        config = Config()
        assert config.reporters == []

    def test_config_reporters(self):
        config = Config(reporters=["ConsoleReporter"])
        assert config.reporters == ["ConsoleReporter"]

    def test_cli_overrides_config(self):
        config = Config(reporters=["OtelReporter"])
        overridden = config.with_overrides(reporters=["ConsoleReporter"])
        assert overridden.reporters == ["ConsoleReporter"]


def test_top_level_help_lists_tests_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "│ tests " in result.stdout
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
    assert "--no-db" in result.stdout
    assert "--otel" in result.stdout


def test_tests_status_help_exposes_status_options():
    result = runner.invoke(app, ["tests", "status", "--help"])
    assert result.exit_code == 0
    assert "--db-path" in result.stdout
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
    sqlite_db_path: Path, sqlite_store: SQLiteStore, monkeypatch
):
    existing_run_id = uuid4()

    sqlite_store.save_run(
        Run(
            run_id=existing_run_id,
            environment=make_environment(),
            result=RunResult(),
        )
    )

    planned = False

    def _build(self, paths, **kwargs):
        nonlocal planned
        planned = True
        return TestSpecCollection(suite_root=Path.cwd())

    async def _fail_run(self, items=None, path=None, run_id=None):
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
            "--db-path",
            str(sqlite_db_path),
            "--run-id",
            str(existing_run_id),
        ],
    )
    assert planned is True
    assert result.exit_code == 2


def test_cli_resolves_reporters_and_injects_store(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(
            self,
            *,
            config,
            reporters,
            store=None,
            fail_fast=False,
            capture_output=True,
        ) -> None:
            captured["config"] = config
            captured["reporters"] = reporters
            captured["store"] = store
            captured["fail_fast"] = fail_fast
            captured["capture_output"] = capture_output

        async def run(self, items, *, run_id=None):
            captured["items"] = items
            captured["run_id"] = run_id
            return Run()

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
            "--db-path",
            str(tmp_path / "rue.db"),
            "--reporter",
            "ConsoleReporter",
            "--show-output",
        ],
    )

    assert result.exit_code == 0
    assert captured["config"].reporters == ["ConsoleReporter"]
    assert [type(r).__name__ for r in captured["reporters"]] == [
        "ConsoleReporter"
    ]
    assert isinstance(captured["store"], SQLiteStore)
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

    result = runner.invoke(
        app, [*command, "--run-id", str(uuid4()), "--no-db"]
    )
    assert result.exit_code == 0


def test_tests_without_subcommand_defaults_to_run(monkeypatch):
    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(
            self,
            *,
            config,
            reporters,
            store=None,
            fail_fast=False,
            capture_output=True,
        ) -> None:
            captured["config"] = config
            captured["reporters"] = reporters
            captured["store"] = store
            captured["fail_fast"] = fail_fast
            captured["capture_output"] = capture_output

        async def run(self, items, *, run_id=None):
            captured["items"] = items
            captured["run_id"] = run_id
            return Run()

    def build_spec_collection(self, paths, **kwargs):
        del self, kwargs
        captured["paths"] = paths
        return TestSpecCollection(suite_root=Path.cwd())

    monkeypatch.setattr(
        "rue.cli.tests.run.load_config", lambda: Config(db_enabled=False)
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
    assert captured["store"] is None


def test_rue_test_command_is_unknown():
    result = runner.invoke(app, ["test", "--no-db"])
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
            "rue.cli.tests.status.command.TestsStatusBuilder.load_items",
            lambda self, collection: [],
        )
        monkeypatch.setattr(
            "rue.cli.tests.status.command.TestsStatusBuilder.build",
            lambda self, collection, items, store=None: TestsStatusReport(),
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
                captured["verbosity"] = kwargs["config"].verbosity

            async def run(self, items, *, run_id=None):
                del items, run_id
                return Run()

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
            "--db-path",
            str(tmp_path / "custom.db"),
        ],
    )

    assert result.exit_code == 0
    assert captured["paths"] == ["tests/sample"]
    assert captured["include_tags"] == ("smoke",)
    assert captured["exclude_tags"] == ("slow",)
    assert captured["keyword"] == "fast and not slow"


def test_tests_status_does_not_create_missing_db(tmp_path, monkeypatch):
    missing_db = tmp_path / "missing.db"

    monkeypatch.setattr(
        "rue.cli.tests.options.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.tests.status.command.TestsStatusBuilder.load_items",
        lambda self, collection: [],
    )
    monkeypatch.setattr(
        "rue.cli.tests.status.command.TestsStatusBuilder.build",
        lambda self, collection, items, store=None: TestsStatusReport(),
    )
    monkeypatch.setattr(
        "rue.cli.tests.status.command.status_renderer.render",
        lambda report, verbosity: "status",
    )

    result = runner.invoke(
        app,
        ["tests", "status", "--db-path", str(missing_db)],
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
