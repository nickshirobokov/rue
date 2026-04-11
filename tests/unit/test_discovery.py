import builtins
from textwrap import dedent

import pytest

from rue.testing.discovery import TestCollector
from rue.config import Config
from rue.resources import registry
from rue.testing.discovery import collect
from rue.testing.runner import Runner


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def test_collect_supports_same_dir_confrue_imports_without_pyproject(
    tmp_path,
):
    (tmp_path / "confrue_shared.py").write_text("VALUE = 123\n")
    (tmp_path / "rue_sample.py").write_text(
        dedent(
            """
            from .confrue_shared import VALUE

            def test_value():
                assert VALUE == 123
            """
        )
    )

    [item] = collect(tmp_path)

    item.fn()


@pytest.mark.asyncio
async def test_collect_autoloads_confrue_chain_in_order(
    tmp_path,
    monkeypatch,
    null_reporter,
):
    monkeypatch.setattr(builtins, "confrue_log", [], raising=False)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'tmp'\nversion = '0.0.0'\n"
    )
    nested = tmp_path / "nested"
    nested.mkdir()

    (tmp_path / "confrue_a.py").write_text(
        dedent(
            """
            import builtins
            import rue

            builtins.confrue_log.append("root-a")

            @rue.resource
            def shared_value():
                return 7
            """
        )
    )
    (tmp_path / "confrue_b.py").write_text(
        dedent(
            """
            import builtins

            from .confrue_a import shared_value

            builtins.confrue_log.append("root-b")
            """
        )
    )
    (nested / "confrue_child.py").write_text(
        dedent(
            """
            import builtins

            from ..confrue_a import shared_value

            builtins.confrue_log.append("child")
            """
        )
    )
    (nested / "rue_sample.py").write_text(
        dedent(
            """
            import builtins

            from ..confrue_a import shared_value

            def test_value(shared_value):
                assert shared_value == 7
                assert builtins.confrue_log == [
                    "root-a",
                    "root-b",
                    "child",
                ]
            """
        )
    )

    items = collect(nested)
    run = await Runner(reporters=[null_reporter]).run(items=items)

    assert run.result.failed == 0
    assert run.result.errors == 0
    assert run.result.passed == 1


@pytest.mark.asyncio
async def test_confrue_session_resources_resolve_hierarchically(
    tmp_path,
    null_reporter,
):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'tmp'\nversion = '0.0.0'\n"
    )
    child = tmp_path / "child"
    sibling = tmp_path / "sibling"
    child.mkdir()
    sibling.mkdir()

    (tmp_path / "confrue_root.py").write_text(
        dedent(
            """
            import rue

            @rue.resource(scope="session")
            def shared_value():
                return "root"
            """
        )
    )
    (child / "confrue_child.py").write_text(
        dedent(
            """
            import rue

            @rue.resource(scope="session")
            def shared_value():
                return "child"
            """
        )
    )
    (tmp_path / "rue_root.py").write_text(
        dedent(
            """
            def test_root(shared_value):
                assert shared_value == "root"
            """
        )
    )
    (child / "rue_child.py").write_text(
        dedent(
            """
            def test_child(shared_value):
                assert shared_value == "child"
            """
        )
    )
    (sibling / "rue_sibling.py").write_text(
        dedent(
            """
            def test_sibling(shared_value):
                assert shared_value == "root"
            """
        )
    )

    items = collect(tmp_path)
    run = await Runner(
        config=Config.model_construct(db_enabled=False),
        reporters=[null_reporter],
    ).run(items=items)

    assert run.result.failed == 0
    assert run.result.errors == 0
    assert run.result.passed == 3


@pytest.mark.asyncio
async def test_same_named_confrue_metrics_preserve_provider_identity_and_modules(
    tmp_path,
    null_reporter,
):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'tmp'\nversion = '0.0.0'\n"
    )
    child = tmp_path / "child"
    child.mkdir()

    (tmp_path / "confrue_root.py").write_text(
        dedent(
            """
            import rue
            from rue import Metric, metrics

            @rue.resource.metric(scope="session")
            def quality():
                metric = Metric()
                yield metric
                yield metric.mean

            def root_check(quality: Metric):
                with metrics(quality):
                    assert True
            """
        )
    )
    (child / "confrue_child.py").write_text(
        dedent(
            """
            import rue
            from rue import Metric, metrics

            @rue.resource.metric(scope="session")
            def quality():
                metric = Metric()
                yield metric
                yield metric.mean

            def child_check(quality: Metric):
                with metrics(quality):
                    assert True
            """
        )
    )
    (tmp_path / "rue_root.py").write_text(
        dedent(
            """
            from rue import metrics

            def test_shared(quality):
                with metrics(quality):
                    assert True
            """
        )
    )
    (child / "rue_child.py").write_text(
        dedent(
            """
            from rue import metrics

            def test_shared(quality):
                with metrics(quality):
                    assert True
            """
        )
    )

    items = collect(tmp_path)
    run = await Runner(
        config=Config.model_construct(db_enabled=False),
        reporters=[null_reporter],
    ).run(items=items)

    metrics = sorted(
        run.result.metric_results,
        key=lambda result: result.metadata.identity.provider_path or "",
    )
    assert len(metrics) == 2
    assert {metric.metadata.identity.name for metric in metrics} == {"quality"}
    assert all(
        metric.metadata.collected_from_tests == {"test_shared"}
        for metric in metrics
    )
    assert metrics[0].metadata.identity != metrics[1].metadata.identity
    module_sets = [metric.metadata.collected_from_modules for metric in metrics]
    assert any(
        any(module.endswith("rue_root.py") for module in modules)
        for modules in module_sets
    )
    assert any(
        any(module.endswith("child/rue_child.py") for module in modules)
        for modules in module_sets
    )


@pytest.mark.asyncio
async def test_collect_runs_class_based_tests_with_resource_injection(
    tmp_path,
    null_reporter,
):
    (tmp_path / "confrue_shared.py").write_text(
        dedent(
            """
            import rue

            @rue.resource
            def shared_value():
                return 7
            """
        )
    )
    module_path = tmp_path / "rue_class_sample.py"
    module_path.write_text(
        dedent(
            """
            class TestMath:
                def test_value(self, shared_value):
                    assert shared_value == 7
            """
        )
    )

    items = collect(module_path)
    run = await Runner(reporters=[null_reporter]).run(items=items)

    assert [item.full_name for item in items] == [
        "rue_class_sample::TestMath::test_value"
    ]
    assert run.result.passed == 1
    assert run.result.executions[0].item.class_name == "TestMath"


def test_collect_items_share_confrue_session_across_selected_modules(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(builtins, "confrue_counter", 0, raising=False)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'tmp'\nversion = '0.0.0'\n"
    )
    (tmp_path / "confrue_root.py").write_text(
        dedent(
            """
            import builtins

            builtins.confrue_counter += 1
            """
        )
    )
    (tmp_path / "rue_good.py").write_text("def test_good():\n    assert True\n")
    (tmp_path / "rue_good_two.py").write_text(
        "def test_good_two():\n    assert True\n"
    )

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "confrue_bad.py").write_text(
        'raise RuntimeError("must not import")\n'
    )
    (bad_dir / "rue_bad.py").write_text("def test_bad():\n    assert True\n")

    items = TestCollector([], [], "good").collect([str(tmp_path)])

    assert [item.name for item in items] == ["test_good", "test_good_two"]
    assert builtins.confrue_counter == 1


def test_collect_does_not_discover_confrue_modules(tmp_path):
    (tmp_path / "confrue_only.py").write_text("VALUE = 1\n")

    assert collect(tmp_path) == []


def test_collect_uses_fresh_import_session_after_file_changes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(builtins, "collected_values", [], raising=False)
    (tmp_path / "confrue_shared.py").write_text("VALUE = 1\n")
    module_path = tmp_path / "rue_sample.py"
    module_path.write_text(
        dedent(
            """
            import builtins
            from .confrue_shared import VALUE

            def test_value():
                builtins.collected_values.append(VALUE)
            """
        )
    )

    [first_item] = collect(tmp_path)
    first_item.fn()
    assert builtins.collected_values == [1]

    builtins.collected_values.clear()
    (tmp_path / "confrue_shared.py").write_text("VALUE = 2\n")

    [second_item] = collect(tmp_path)
    second_item.fn()
    assert builtins.collected_values == [2]
