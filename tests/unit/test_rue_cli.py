from pathlib import Path
from uuid import uuid4

from tomlkit import parse
from typer.testing import CliRunner

from rue.cli import app
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


def test_resolve_otel_defaults_to_enabled():
    result = runner.invoke(app, ["test", "--no-db", "--help"])
    assert result.exit_code == 0


def test_cli_otel_flag_parsing():
    config = Config(otel=False)
    overridden = config.with_overrides(otel=True)
    assert overridden.otel is True


def test_cli_no_otel_flag_overrides_config():
    config = Config(otel=True)
    overridden = config.with_overrides(otel=False)
    assert overridden.otel is False


def test_cli_rejects_invalid_run_id():
    result = runner.invoke(app, ["test", "--run-id", "not-a-uuid"])
    assert result.exit_code == 2


def test_run_tests_returns_2_when_run_id_already_exists(
    sqlite_db_path: Path, sqlite_store: SQLiteStore, monkeypatch
):
    existing_run_id = uuid4()

    sqlite_store.save_run(
        Run(
            run_id=existing_run_id,
            environment=RunEnvironment(rue_version="1.0.0"),
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
        "rue.cli.TestSpecCollector.build_spec_collection", _build
    )
    monkeypatch.setattr(
        "rue.cli.TestLoader.load_from_collection",
        lambda self, collection: [make_item("test_ok", set())],
    )
    monkeypatch.setattr("rue.cli.Runner.run", _fail_run)

    result = runner.invoke(
        app,
        [
            "test",
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
        "rue.cli.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.TestLoader.load_from_collection",
        lambda self, collection: [make_item("test_ok", set())],
    )
    monkeypatch.setattr("rue.cli.Runner", FakeRunner)

    result = runner.invoke(
        app,
        [
            "test",
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


def test_run_tests_keeps_normal_exit_code_when_run_id_is_unique(monkeypatch):
    monkeypatch.setattr(
        "rue.cli.TestSpecCollector.build_spec_collection",
        lambda self, paths, **kwargs: TestSpecCollection(suite_root=Path.cwd()),
    )
    monkeypatch.setattr(
        "rue.cli.TestLoader.load_from_collection",
        lambda self, collection: [make_item("test_ok", set())],
    )

    result = runner.invoke(app, ["test", "--run-id", str(uuid4()), "--no-db"])
    assert result.exit_code == 0


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
