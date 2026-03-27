from argparse import Namespace
from pathlib import Path
from textwrap import dedent
from uuid import uuid4

import pytest

from rue.cli import (
    KeywordMatcher,
    _build_parser,
    _collect_items,
    _filter_items,
    _resolve_otel,
    _resolve_otel_content,
    _resolve_reporters,
    _run_tests,
)
from rue.config import Config
from rue.storage.sqlite import SQLiteStore
from rue.testing.discovery import TestItem, collect_static
from rue.testing.models.run import Run, RunEnvironment, RunResult


def dummy() -> None:  # Helper for TestItem.fn
    return None


def make_item(name: str, tags: set[str], suffix: str | None = None) -> TestItem:
    return TestItem(
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

    filtered = _filter_items(
        items, include_tags=["smoke"], exclude_tags=[], keyword=None
    )
    assert [item.name for item in filtered] == ["test_fast"]

    filtered = _filter_items(
        items, include_tags=[], exclude_tags=["slow"], keyword=None
    )
    assert [item.name for item in filtered] == ["test_fast"]

    filtered = _filter_items(
        items, include_tags=[], exclude_tags=[], keyword="slow"
    )
    assert [item.name for item in filtered] == ["test_slow"]


def test_collect_static_extracts_names_and_tags(tmp_path):
    module_path = tmp_path / "rue_sample.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import tag

            @tag("smoke")
            def test_top():
                pass

            @rue.tag("suite")
            class TestFlows:
                @tag("fast")
                def test_nested(self):
                    pass
            """
        )
    )

    refs = collect_static(module_path)
    refs_by_name = {ref.full_name: ref for ref in refs}

    assert "rue_sample::test_top" in refs_by_name
    assert refs_by_name["rue_sample::test_top"].tags == frozenset({"smoke"})

    assert "rue_sample::TestFlows::test_nested" in refs_by_name
    assert refs_by_name["rue_sample::TestFlows::test_nested"].tags == frozenset(
        {"suite", "fast"}
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

    items = _collect_items(
        paths=[str(tmp_path)],
        include_tags=[],
        exclude_tags=[],
        keyword="good",
    )

    assert len(items) == 1
    assert items[0].name == "test_good"


def test_collect_items_same_file_ignores_unselected_invalid_test(tmp_path):
    mixed_module = tmp_path / "rue_mixed.py"
    mixed_module.write_text(
        dedent(
            """
            import rue
            from rue import iter_cases

            def test_good():
                assert True

            @iter_cases()
            def test_bad(case):
                assert case
            """
        )
    )

    items = _collect_items(
        paths=[str(tmp_path)],
        include_tags=[],
        exclude_tags=[],
        keyword="good",
    )

    assert len(items) == 1
    assert items[0].name == "test_good"


class TestResolveReporters:
    """Tests for _resolve_reporters function."""

    def _make_args(self, **kwargs) -> Namespace:
        defaults = {"reporters": None}
        defaults.update(kwargs)
        return Namespace(**defaults)

    def _make_config(self, **kwargs) -> Config:
        return Config(**kwargs)

    def test_default_console_and_otel_reporters(self):
        args = self._make_args()
        config = self._make_config()
        reporters = _resolve_reporters(args, config)
        assert reporters == []

    def test_config_reporters(self):
        args = self._make_args()
        config = self._make_config(reporters=["ConsoleReporter"])
        reporters = _resolve_reporters(args, config)
        assert reporters == ["ConsoleReporter"]

    def test_cli_overrides_config(self):
        args = self._make_args(reporters=["ConsoleReporter"])
        config = self._make_config(reporters=["OtelReporter"])
        reporters = _resolve_reporters(args, config)
        assert reporters == ["ConsoleReporter"]


def _make_cli_config() -> Config:
    return Config()


def test_resolve_otel_settings_prefer_cli_over_config():
    parser = _build_parser()
    args = parser.parse_args(["test", "--no-otel", "--otel-content"])
    config = Config(otel=True, otel_content=False)

    assert _resolve_otel(args, config) is False
    assert _resolve_otel_content(args, config) is True


def test_parser_rejects_invalid_run_id():
    parser = _build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["test", "--run-id", "not-a-uuid"])
    assert exc.value.code == 2


@pytest.mark.asyncio
async def test_run_tests_returns_2_when_run_id_already_exists(
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

    parser = _build_parser()
    args = parser.parse_args(
        [
            "test",
            "--db-path",
            str(sqlite_db_path),
            "--run-id",
            str(existing_run_id),
        ]
    )
    config = _make_cli_config()

    collected = False

    def _collect(_paths, _include_tags, _exclude_tags, _keyword):
        nonlocal collected
        collected = True
        return [make_item("test_ok", set())]

    async def _fail_run(self, items=None, path=None, run_id=None):
        _ = self, items, path, run_id
        msg = "Runner.run should not be called when duplicate run_id exists"
        raise AssertionError(msg)

    monkeypatch.setattr("rue.cli._collect_items", _collect)
    monkeypatch.setattr("rue.cli.Runner.run", _fail_run)

    exit_code = await _run_tests(args, config)
    assert collected is True
    assert exit_code == 2


@pytest.mark.asyncio
async def test_run_tests_keeps_normal_exit_code_when_run_id_is_unique(
    monkeypatch,
):
    parser = _build_parser()
    args = parser.parse_args(["test", "--run-id", str(uuid4()), "--no-db"])
    config = _make_cli_config()

    monkeypatch.setattr(
        "rue.cli._collect_items",
        lambda _paths, _include_tags, _exclude_tags, _keyword: [
            make_item("test_ok", set())
        ],
    )

    exit_code = await _run_tests(args, config)
    assert exit_code == 0
