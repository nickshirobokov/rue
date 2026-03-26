import builtins
from textwrap import dedent

import pytest

from rue.cli import _collect_items
from rue.resources import clear_registry
from rue.testing.discovery import collect
from rue.testing.runner import Runner


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


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

    items = _collect_items([str(tmp_path)], [], [], "good")

    assert [item.name for item in items] == ["test_good", "test_good_two"]
    assert builtins.confrue_counter == 1


def test_collect_does_not_discover_confrue_modules(tmp_path):
    (tmp_path / "confrue_only.py").write_text("VALUE = 1\n")

    assert collect(tmp_path) == []
