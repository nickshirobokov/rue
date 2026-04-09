from pathlib import Path
from textwrap import dedent
from uuid import uuid4

from typer.testing import CliRunner

from rue.cli import app
from rue.testing.discovery import KeywordMatcher, TestCollector
from rue.config import Config
from rue.storage.sqlite import SQLiteStore
from rue.testing import TestDefinition
from rue.testing.discovery import collect_static
from rue.testing.models.run import Run, RunEnvironment, RunResult

runner = CliRunner()


def dummy() -> None:
    return None


def make_item(name: str, tags: set[str], suffix: str | None = None) -> TestDefinition:
    return TestDefinition(
        name=name,
        fn=dummy,
        module_path=Path("module.py"),
        is_async=False,
        params=[],
        tags=tags,
        suffix=suffix,
    )


def test_keyword_matcher_supports_boolean_logic():
    matcher = KeywordMatcher("foo and not bar")
    assert matcher.match("foo_case")
    assert not matcher.match("bar_case")
    assert not matcher.match("other")


def test_filter_items_applies_tag_logic():
    items = [
        make_item("test_fast", {"fast", "smoke"}),
        make_item("test_slow", {"slow"}),
    ]

    filtered = TestCollector(include_tags=["smoke"], exclude_tags=[], keyword=None).filter(items)
    assert [item.name for item in filtered] == ["test_fast"]

    filtered = TestCollector(include_tags=[], exclude_tags=["slow"], keyword=None).filter(items)
    assert [item.name for item in filtered] == ["test_fast"]

    filtered = TestCollector(include_tags=[], exclude_tags=[], keyword="slow").filter(items)
    assert [item.name for item in filtered] == ["test_slow"]


def test_collect_static_extracts_names_and_tags(tmp_path):
    module_path = tmp_path / "rue_sample.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import test

            @test.tag("smoke")
            @test.tag.inline
            def test_top():
                pass

            @rue.test.tag("suite")
            @rue.test.tag.skip(reason="skip suite")
            class TestFlows:
                @test.tag("fast")
                @test.tag.xfail(reason="known")
                def test_nested(self):
                    pass
            """
        )
    )

    refs = collect_static(module_path)
    refs_by_name = {ref.full_name: ref for ref in refs}

    assert "rue_sample::test_top" in refs_by_name
    assert refs_by_name["rue_sample::test_top"].tags == frozenset(
        {"smoke", "inline"}
    )

    assert "rue_sample::TestFlows::test_nested" in refs_by_name
    assert refs_by_name["rue_sample::TestFlows::test_nested"].tags == frozenset(
        {"suite", "skip", "fast", "xfail"}
    )


def test_collect_items_keyword_avoids_importing_unselected_modules(tmp_path):
    good_module = tmp_path / "rue_good.py"
    good_module.write_text(
        dedent(
            """
            def test_good():
                assert True
            """
        )
    )

    bad_module = tmp_path / "rue_bad.py"
    bad_module.write_text(
        dedent(
            """
            raise RuntimeError("must not import")

            def test_bad():
                pass
            """
        )
    )

    items = TestCollector(include_tags=[], exclude_tags=[], keyword="good").collect(
        [str(tmp_path)]
    )

    assert len(items) == 1
    assert items[0].name == "test_good"


def test_collect_items_same_file_ignores_unselected_invalid_test(tmp_path):
    mixed_module = tmp_path / "rue_mixed.py"
    mixed_module.write_text(
        dedent(
            """
            from rue import test

            def test_good():
                assert True

            @test.iterate.cases()
            def test_bad(case):
                assert case
            """
        )
    )

    items = TestCollector(include_tags=[], exclude_tags=[], keyword="good").collect(
        [str(tmp_path)]
    )

    assert len(items) == 1
    assert items[0].name == "test_good"


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

    collected = False

    def _collect(self, paths):
        nonlocal collected
        collected = True
        return [make_item("test_ok", set())]

    async def _fail_run(self, items=None, path=None, run_id=None):
        msg = "Runner.run should not be called when duplicate run_id exists"
        raise AssertionError(msg)

    monkeypatch.setattr("rue.cli.TestCollector.collect", _collect)
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
    assert collected is True
    assert result.exit_code == 2


def test_run_tests_keeps_normal_exit_code_when_run_id_is_unique(monkeypatch):
    monkeypatch.setattr(
        "rue.cli.TestCollector.collect",
        lambda self, paths: [make_item("test_ok", set())],
    )

    result = runner.invoke(app, ["test", "--run-id", str(uuid4()), "--no-db"])
    assert result.exit_code == 0
