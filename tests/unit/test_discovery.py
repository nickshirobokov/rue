import builtins
import sys
from dataclasses import replace
from pathlib import Path
from textwrap import dedent
from uuid import UUID, uuid4

import pytest

from rue.context.runtime import TestContext
from rue.resources import DependencyResolver, Scope, registry
from rue.testing.compilation.modifiers import (
    BackendModifier,
    ParameterSet,
    ParamsIterateModifier,
)
from rue.testing.discovery import (
    KeywordMatcher,
    TestDefinitionErrors,
    TestLoader,
    TestSpecCollector,
)
from rue.testing.execution.backend import ExecutionBackend
from rue.testing.execution.suite.executable import ExecutableSuite
from rue.testing.models import Locator, TestSpec
from tests.helpers import make_suite_context


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
    suitespec = TestSpecCollector((), (), None).collect_test_specs((path,))
    return TestLoader(suitespec.suite_root).load_tests(suitespec)


def test_load_tests_preserves_synthetic_module_file_metadata(tmp_path):
    write_files(
        tmp_path,
        {
            "test_file_metadata.py": """
                from rue import test

                @test
                def test_metadata():
                    assert True
            """
        },
    )

    [loaded] = materialize(tmp_path / "test_file_metadata.py")
    module = sys.modules[loaded.fn.__module__]

    assert loaded.fn.__module__.startswith("rue_discovery.suite_")
    assert Path(module.__file__) == (
        tmp_path / "test_file_metadata.py"
    ).resolve()
    assert module.__spec__ is not None
    assert module.__spec__.has_location is True


async def execute_items(items):
    context = make_suite_context()
    return await ExecutableSuite(
        items=items,
        suite_execution_id=context.suite_execution_id,
        resolver=DependencyResolver(registry),
    ).execute()


def test_spec_labels_are_bounded_and_keep_full_case_id():
    case_id = UUID("00000000-0000-0000-0000-000000000001")
    spec = TestSpec(
        locator=Locator(Path(__file__), "test_case"),
        is_async=False,
        params=(),
        modifiers=(),
        tags=frozenset(),
        suffix="case-with-very-long-metadata-slug-that-needs-trimming",
        case_id=case_id,
    )

    assert (
        spec.get_label()
        == "case-with-very-long-metadata-slug-that-needs-trim…"
    )
    assert spec.get_label(full=True) == f"case-with-… | {case_id}"
    assert spec.get_label(full=True, length=44, separator=" / ") == (
        f"case… / {case_id}"
    )
    assert spec.get_label(full=True, length=36) == str(case_id)
    assert len(spec.get_label()) == 50
    assert len(spec.get_label(full=True)) == 50
    assert str(case_id) in spec.get_label(full=True)


def test_selector_filters_by_tags_and_keyword():
    items = [
        TestSpec(
            locator=Locator(Path(__file__), "test_fast"),
            is_async=False,
            params=(),
            modifiers=(),
            tags=frozenset({"fast", "smoke"}),
        ),
        TestSpec(
            locator=Locator(Path(__file__), "test_slow"),
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

    assert [item.locator.function_name for item in selected] == ["test_fast"]


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

    suitespec = TestSpecCollector((), (), None).collect_test_specs(
        (tmp_path,), explicit_root=tmp_path
    )
    specs_by_name = {spec.full_name: spec.tags for spec in suitespec.specs}

    assert suitespec.suite_root == tmp_path
    assert [spec.collection_index for spec in suitespec.specs] == [0, 1, 2, 3]
    assert specs_by_name == {
        "test_sample::helper": frozenset(),
        "test_sample::test_top": frozenset({"smoke"}),
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
        for spec in TestSpecCollector((), (), None)
        .collect_test_specs((tmp_path,))
        .specs
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

    suitespec = TestSpecCollector([], [], "good").collect_test_specs(
        [str(tmp_path)]
    )
    items = TestLoader(suitespec.suite_root).load_tests(suitespec)

    assert [item.spec.locator.function_name for item in items] == ["test_good"]


def test_load_tests_skips_unselected_invalid_tests_in_same_module(
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

    suitespec = TestSpecCollector([], [], "good").collect_test_specs(
        [str(tmp_path)]
    )
    items = TestLoader(suitespec.suite_root).load_tests(suitespec)

    assert [item.spec.locator.function_name for item in items] == ["test_good"]


def test_load_tests_enriches_runtime_metadata(tmp_path):
    write_files(
        tmp_path,
        {
            "test_metadata.py": """
                from rue import test

                @test.backend("main")
                @test.tag.skip(reason="skip me")
                @test.iterate.params("value", [1], ids=["one"])
                def test_main_skip(value):
                    assert value == 1

                @test.tag.xfail(reason="known", strict=True)
                def test_expected_failure():
                    assert False

                @test.iterate.params("value", [])
                def test_bad(value):
                    assert value

                @test.backend("main")
                @test.backend("subprocess")
                def test_duplicate_backend():
                    assert True
            """
        },
    )

    suitespec = TestSpecCollector((), (), None).collect_test_specs(
        (tmp_path / "test_metadata.py",)
    )
    specs_by_function_name = {spec.locator.function_name: spec for spec in suitespec.specs}

    assert specs_by_function_name["test_main_skip"].params == ()
    assert specs_by_function_name["test_main_skip"].skip_reason is None
    assert specs_by_function_name["test_main_skip"].modifiers == ()
    assert specs_by_function_name["test_expected_failure"].xfail_reason is None
    valid_suitespec = replace(
        suitespec,
        specs=tuple(
            spec
            for spec in suitespec.specs
            if spec.locator.function_name
            in {"test_main_skip", "test_expected_failure"}
        ),
    )
    items = TestLoader(valid_suitespec.suite_root).load_tests(valid_suitespec)
    items_by_name = {item.spec.locator.function_name: item for item in items}
    backend_modifier, params_modifier = items_by_name[
        "test_main_skip"
    ].spec.modifiers

    assert items_by_name["test_main_skip"].spec.params == ("value",)
    assert items_by_name["test_main_skip"].spec.skip_reason == "skip me"
    assert backend_modifier == BackendModifier(ExecutionBackend.MAIN)
    assert isinstance(params_modifier, ParamsIterateModifier)
    assert params_modifier.parameter_sets == (
        ParameterSet(values={"value": 1}, suffix="one"),
    )
    assert items_by_name["test_expected_failure"].spec.xfail_reason == "known"
    assert items_by_name["test_expected_failure"].spec.xfail_strict is True
    with pytest.raises(TestDefinitionErrors) as raised:
        TestLoader(suitespec.suite_root).load_tests(suitespec)
    messages = {str(issue) for issue in raised.value.exceptions}
    assert any(
        "test_bad" in message
        and "iterate.params() requires at least one value set" in message
        for message in messages
    )
    assert any(
        "test_duplicate_backend" in message
        and "Multiple @rue.test.backend(...) decorators are not supported."
        in message
        for message in messages
    )


def test_load_tests_raises_setup_failures(tmp_path):
    write_files(
        tmp_path,
        {
            "bad/conftest.py": 'raise RuntimeError("bad setup")\n',
            "bad/test_bad.py": """
                import rue

                @rue.test
                def test_bad():
                    pass
            """,
        },
    )

    suitespec = TestSpecCollector((), (), None).collect_test_specs((tmp_path,))

    with pytest.raises(TestDefinitionErrors) as raised:
        TestLoader(suitespec.suite_root).load_tests(suitespec)

    [issue] = raised.value.exceptions
    assert issue.spec.full_name == "test_bad::test_bad"
    assert issue.message == "bad setup"


def test_load_tests_raises_missing_callable(tmp_path):
    write_files(
        tmp_path,
        {
            "test_sample.py": """
                import rue

                @rue.test
                def test_good():
                    pass

                @rue.test
                def test_bad():
                    pass
            """,
        },
    )

    original_suitespec = TestSpecCollector((), (), None).collect_test_specs(
        (tmp_path,)
    )
    bad_spec = replace(
        original_suitespec.specs[1],
        locator=Locator(
            module_path=original_suitespec.specs[1].locator.module_path,
            function_name="missing_test",
        ),
    )
    suitespec = replace(
        original_suitespec,
        specs=(original_suitespec.specs[0], bad_spec),
    )

    with pytest.raises(TestDefinitionErrors) as raised:
        TestLoader(suitespec.suite_root).load_tests(suitespec)

    [issue] = raised.value.exceptions
    assert issue.spec.locator.function_name == "missing_test"
    assert "missing_test" in issue.message


def test_load_tests_raises_non_callable_target(tmp_path):
    write_files(
        tmp_path,
        {
            "test_sample.py": """
                import rue

                not_callable = 1

                @rue.test
                def test_good():
                    pass
            """,
        },
    )

    original_suitespec = TestSpecCollector((), (), None).collect_test_specs(
        (tmp_path,)
    )
    bad_spec = replace(
        original_suitespec.specs[0],
        locator=Locator(
            module_path=original_suitespec.specs[0].locator.module_path,
            function_name="not_callable",
        ),
    )
    suitespec = replace(original_suitespec, specs=(bad_spec,))

    with pytest.raises(TestDefinitionErrors) as raised:
        TestLoader(suitespec.suite_root).load_tests(suitespec)

    [issue] = raised.value.exceptions
    assert issue.spec.locator.function_name == "not_callable"
    assert "not a function or method" in issue.message


@pytest.mark.asyncio
async def test_materialize_supports_same_dir_setup_without_pyproject(
    tmp_path,
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

    suite = await execute_items(materialize(tmp_path))

    assert suite.result.passed == 1
    assert suite.result.failed == 0
    assert suite.result.errors == 0


@pytest.mark.asyncio
async def test_materialize_supports_setup_imports_from_suite_root(
    tmp_path,
    monkeypatch,
):
    write_files(
        tmp_path,
        {
            "pyproject.toml": "[project]\nname = 'tmp'\nversion = '0.0.0'\n",
            "tests/helpers.py": 'VALUE = "project-helper"\n',
            "tests/conftest.py": """
                import rue

                from tests.helpers import VALUE

                @rue.resource
                def project_value():
                    return VALUE
            """,
            "tests/test_sample.py": """
                import rue

                @rue.test
                def test_value(project_value):
                    assert project_value == "project-helper"

                @rue.test.backend("subprocess")
                def test_subprocess_value(project_value):
                    assert project_value == "project-helper"
            """,
        },
    )
    monkeypatch.delitem(sys.modules, "tests.helpers", raising=False)

    items = materialize(tmp_path / "tests")
    assert {item.spec.name for item in items} == {
        "test_value",
        "test_subprocess_value",
    }
    assert all("rue_discovery" in item.fn.__module__ for item in items)

    suite = await execute_items(items)

    assert suite.result.passed == 2
    assert suite.result.failed == 0
    assert suite.result.errors == 0


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

    suitespec = TestSpecCollector((), (), None).collect_test_specs(
        (tmp_path / "nested",)
    )
    [item] = TestLoader(suitespec.suite_root).load_tests(suitespec)

    assert item.suite_root == suitespec.suite_root
    assert item.setup_chain == suitespec.setup_chains[item.spec.locator.module_path]

    make_suite_context()
    with TestContext(test_execution_id=uuid4()):
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

    assert [item.spec.full_name for item in materialize(tmp_path)] == [
        "test_class_sample::MathChecks::test_value",
        "test_class_sample::MathChecks::helper",
        "test_class_sample::HelperSuite::extra",
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

    suitespec = TestSpecCollector([], [], "good").collect_test_specs(
        [str(tmp_path)]
    )
    items = TestLoader(suitespec.suite_root).load_tests(suitespec)

    assert [item.spec.locator.function_name for item in items] == [
        "test_good",
        "test_good_two",
    ]
    assert builtins.confrue_counter == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture_location", ["module", "conftest"])
async def test_materialize_promotes_pytest_fixtures(
    tmp_path,
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

    suite = await execute_items(materialize(tmp_path))

    assert suite.result.passed == 1
    assert suite.result.failed == 0
    assert suite.result.errors == 0


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


def test_materialize_rewrites_pytest_fixture_aliases_to_resources(tmp_path):
    write_files(
        tmp_path,
        {
            "test_sample.py": """
                import pytest as pt
                import rue

                @pt.fixture(scope="module")
                def greeting():
                    return "hello"

                @rue.test
                def test_uses_fixture(greeting):
                    assert greeting == "hello"
            """
        },
    )

    [item] = materialize(tmp_path)

    assert item.spec.locator.function_name == "test_uses_fixture"
    test_execution_id = uuid4()
    graphs = registry.compile_graphs(
        {test_execution_id: (item.spec, ("greeting",))}
    )
    graph = graphs[test_execution_id]
    greeting = registry.get_definition(
        graph.injections["greeting"]
    )
    assert greeting.spec.scope == Scope.MODULE
