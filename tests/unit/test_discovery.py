import builtins
from pathlib import Path
from textwrap import dedent

import pytest

from rue.resources import registry
from rue.testing.discovery import KeywordMatcher, TestLoader, TestSpecCollector
from rue.testing.models import (
    ParameterSet,
    ParamsIterateModifier,
    TestLocator,
    TestSpec,
)
from rue.testing.runner import Runner


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def write_files(root, files):
    for relative_path, source in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(source))


def materialize(path):
    plan = TestSpecCollector((), (), None).build_spec_collection((path,))
    return TestLoader(plan.suite_root, registry=registry).materialize_plan(plan)


def test_selector_filters_by_tags_and_keyword():
    items = [
        TestSpec(
            locator=TestLocator(Path("test_sample.py"), "test_fast"),
            is_async=False,
            params=(),
            modifiers=(),
            tags=frozenset({"fast", "smoke"}),
        ),
        TestSpec(
            locator=TestLocator(Path("test_sample.py"), "test_slow"),
            is_async=False,
            params=(),
            modifiers=(),
            tags=frozenset({"slow"}),
        ),
    ]

    assert KeywordMatcher("fast and not slow").match("test_fast")
    assert not KeywordMatcher("fast and not slow").match("test_slow")

    selected = TestSpecCollector(["smoke"], ["slow"], "fast").filter_specs(
        items
    )

    assert [item.name for item in selected] == ["test_fast"]


def test_selector_plan_discovers_rue_tests_and_static_tags(tmp_path):
    write_files(
        tmp_path,
        {
            "test_sample.py": """
                import rue
                from rue import test

                def test_pytest_only():
                    pass

                @rue.test
                def helper():
                    pass

                @test.tag("smoke")
                @test.tag.inline
                def test_top():
                    pass

                @rue.test.tag("suite")
                @rue.test.tag.skip(reason="skip suite")
                class Flows:
                    @test.tag("fast")
                    @test.tag.xfail(reason="known")
                    def test_nested(self):
                        pass

                    @rue.test
                    def helper_nested(self):
                        pass
            """
        },
    )

    plan = TestSpecCollector((), (), None).build_spec_collection(
        (tmp_path,), explicit_root=tmp_path
    )
    specs_by_name = {spec.full_name: spec.tags for spec in plan.specs}

    assert plan.suite_root == tmp_path
    assert specs_by_name == {
        "test_sample::helper": frozenset(),
        "test_sample::test_top": frozenset({"smoke", "inline"}),
        "test_sample::Flows::test_nested": frozenset(
            {"suite", "skip", "fast", "xfail"}
        ),
        "test_sample::Flows::helper_nested": frozenset({"suite", "skip"}),
    }


def test_selector_plan_ignores_setup_and_legacy_modules(tmp_path):
    write_files(
        tmp_path,
        {
            "conftest.py": "VALUE = 1\n",
            "confrue_only.py": "VALUE = 2\n",
            "rue_legacy.py": """
                import rue

                @rue.test
                def test_old():
                    pass
            """,
            "test_real.py": """
                import rue

                @rue.test
                def test_real():
                    pass
            """,
        },
    )

    assert [
        spec.full_name
        for spec in TestSpecCollector((), (), None).build_spec_collection((tmp_path,)).specs
    ] == ["test_real::test_real"]


def test_selector_skips_unselected_modules_before_import(tmp_path):
    write_files(
        tmp_path,
        {
            "test_good.py": """
                import rue

                @rue.test
                def test_good():
                    assert True
            """,
            "test_bad.py": """
                import rue

                raise RuntimeError("must not import")

                @rue.test
                def test_bad():
                    pass
            """,
        },
    )

    plan = TestSpecCollector([], [], "good").build_spec_collection([str(tmp_path)])
    items = TestLoader(plan.suite_root, registry=registry).materialize_plan(plan)

    assert [item.name for item in items] == ["test_good"]


def test_materialize_plan_skips_unselected_invalid_tests_in_same_module(
    tmp_path,
):
    write_files(
        tmp_path,
        {
            "test_mixed.py": """
                from rue import test

                @test
                def test_good():
                    assert True

                @test.iterate.cases()
                def test_bad(case):
                    assert case
            """
        },
    )

    plan = TestSpecCollector([], [], "good").build_spec_collection([str(tmp_path)])
    items = TestLoader(plan.suite_root, registry=registry).materialize_plan(plan)

    assert [item.name for item in items] == ["test_good"]


def test_materialize_plan_enriches_runtime_metadata(tmp_path):
    write_files(
        tmp_path,
        {
            "test_metadata.py": """
                from rue import test

                @test.tag.inline
                @test.tag.skip(reason="skip me")
                @test.iterate.params("value", [1], ids=["one"])
                def test_inline_skip(value):
                    assert value == 1

                @test.tag.xfail(reason="known", strict=True)
                def test_expected_failure():
                    assert False

                @test.iterate.params("value", [])
                def test_bad(value):
                    assert value
            """
        },
    )

    plan = TestSpecCollector((), (), None).build_spec_collection((tmp_path / "test_metadata.py",))
    planned_specs = {spec.name: spec for spec in plan.specs}

    assert planned_specs["test_inline_skip"].params == ()
    assert planned_specs["test_inline_skip"].skip_reason is None
    assert planned_specs["test_inline_skip"].inline is False
    assert planned_specs["test_expected_failure"].xfail_reason is None
    assert planned_specs["test_bad"].definition_error is None

    items = TestLoader(plan.suite_root, registry=registry).materialize_plan(plan)
    items_by_name = {item.name: item for item in items}
    [modifier] = items_by_name["test_inline_skip"].modifiers

    assert items_by_name["test_inline_skip"].params == ("value",)
    assert items_by_name["test_inline_skip"].skip_reason == "skip me"
    assert items_by_name["test_inline_skip"].inline is True
    assert isinstance(modifier, ParamsIterateModifier)
    assert modifier.parameter_sets == (
        ParameterSet(values={"value": 1}, suffix="one"),
    )
    assert items_by_name["test_expected_failure"].xfail_reason == "known"
    assert items_by_name["test_expected_failure"].xfail_strict is True
    assert (
        items_by_name["test_bad"].definition_error
        == "iterate.params() requires at least one value set"
    )


@pytest.mark.asyncio
async def test_materialize_supports_same_dir_setup_without_pyproject(
    tmp_path,
    null_reporter,
):
    write_files(
        tmp_path,
        {
            "conftest.py": """
                import rue

                VALUE = 123

                @rue.resource
                def shared_value():
                    return VALUE
            """,
            "confrue_shared.py": "FLAG = 456\n",
            "test_sample.py": """
                import rue

                from .confrue_shared import FLAG
                from .conftest import VALUE

                @rue.test
                def test_value(shared_value):
                    assert VALUE == 123
                    assert FLAG == 456
                    assert shared_value == VALUE
            """,
        },
    )

    run = await Runner(reporters=[null_reporter]).run(items=materialize(tmp_path))

    assert run.result.passed == 1
    assert run.result.failed == 0
    assert run.result.errors == 0


def test_materialize_imports_nested_setup_chain_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(builtins, "setup_log", [], raising=False)
    write_files(
        tmp_path,
        {
            "pyproject.toml": "[project]\nname = 'tmp'\nversion = '0.0.0'\n",
            "conftest.py": """
                import builtins

                ROOT_VALUE = 3
                builtins.setup_log.append("root-conftest")
            """,
            "confrue_root.py": """
                import builtins

                from .conftest import ROOT_VALUE

                builtins.setup_log.append(f"root-confrue:{ROOT_VALUE}")
            """,
            "nested/conftest.py": """
                import builtins

                from ..conftest import ROOT_VALUE

                CHILD_VALUE = ROOT_VALUE + 1
                builtins.setup_log.append(f"child-conftest:{CHILD_VALUE}")
            """,
            "nested/confrue_child.py": """
                import builtins

                from .conftest import CHILD_VALUE

                builtins.setup_log.append(f"child-confrue:{CHILD_VALUE}")
            """,
            "nested/test_sample.py": """
                import builtins
                import rue

                from .conftest import CHILD_VALUE

                builtins.setup_log.append("test-module")

                @rue.test
                def test_value():
                    assert CHILD_VALUE == 4
                    assert builtins.setup_log == [
                        "root-conftest",
                        "root-confrue:3",
                        "child-conftest:4",
                        "child-confrue:4",
                        "test-module",
                    ]
            """,
        },
    )

    [item] = materialize(tmp_path / "nested")

    item.fn()


def test_materialize_collects_class_based_and_method_marked_tests(tmp_path):
    write_files(
        tmp_path,
        {
            "test_class_sample.py": """
                import rue

                @rue.test
                class MathChecks:
                    def test_value(self):
                        assert True

                    @rue.test
                    def helper(self):
                        assert True

                class HelperSuite:
                    def test_pytest_only(self):
                        assert False

                    @rue.test
                    def extra(self):
                        assert True
            """
        },
    )

    assert [item.full_name for item in materialize(tmp_path)] == [
        "test_class_sample::HelperSuite::extra",
        "test_class_sample::MathChecks::helper",
        "test_class_sample::MathChecks::test_value",
    ]


def test_materialize_uses_single_session_for_selected_modules(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(builtins, "confrue_counter", 0, raising=False)
    write_files(
        tmp_path,
        {
            "pyproject.toml": "[project]\nname = 'tmp'\nversion = '0.0.0'\n",
            "confrue_root.py": """
                import builtins

                builtins.confrue_counter += 1
            """,
            "test_good.py": """
                from rue import test

                @test
                def test_good():
                    assert True
            """,
            "test_good_two.py": """
                from rue import test

                @test
                def test_good_two():
                    assert True
            """,
            "bad/confrue_bad.py": 'raise RuntimeError("must not import")\n',
            "bad/test_bad.py": """
                from rue import test

                raise RuntimeError("must not import")

                @test
                def test_bad():
                    assert True
            """,
        },
    )

    plan = TestSpecCollector([], [], "good").build_spec_collection([str(tmp_path)])
    items = TestLoader(plan.suite_root, registry=registry).materialize_plan(plan)

    assert [item.name for item in items] == ["test_good", "test_good_two"]
    assert builtins.confrue_counter == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture_location", ["module", "conftest"])
async def test_materialize_promotes_pytest_fixtures(
    tmp_path,
    null_reporter,
    fixture_location,
):
    files = {
        "test_sample.py": """
            import rue

            @rue.test
            def test_uses_fixture(greeting):
                assert greeting == "hello"
        """
    }

    if fixture_location == "module":
        files["test_sample.py"] = """
            import pytest
            import rue

            @pytest.fixture
            def greeting():
                return "hello"

            @rue.test
            def test_uses_fixture(greeting):
                assert greeting == "hello"
        """
    else:
        files["conftest.py"] = """
            import pytest

            @pytest.fixture
            def greeting():
                return "hello"
        """

    write_files(tmp_path, files)

    run = await Runner(reporters=[null_reporter]).run(items=materialize(tmp_path))

    assert run.result.passed == 1
    assert run.result.failed == 0
    assert run.result.errors == 0


def test_materialize_uses_deterministic_module_names(tmp_path):
    write_files(
        tmp_path,
        {
            "test_sample.py": """
                import rue

                @rue.test
                def test_value():
                    pass
            """
        },
    )

    [first_item] = materialize(tmp_path)
    [second_item] = materialize(tmp_path)

    assert first_item.fn.__module__ == second_item.fn.__module__
    assert "rue_discovery" in first_item.fn.__module__
