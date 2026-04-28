import builtins
from dataclasses import replace
from pathlib import Path
from textwrap import dedent
from uuid import UUID, uuid4

import pytest

from rue.context.runtime import TestContext
from rue.resources import ResourceResolver, Scope, registry
from rue.testing.discovery import (
    KeywordMatcher,
    TestDefinitionErrors,
    TestLoader,
    TestSpecCollector,
)
from rue.testing.execution.base import ExecutionBackend
from rue.testing.models import (
    BackendModifier,
    Locator,
    ParameterSet,
    ParamsIterateModifier,
    TestSpec,
)
from rue.testing.runner import Runner
from tests.unit.factories import make_run_context


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
    return TestLoader(plan.suite_root).load_from_collection(plan)


def make_runner(null_reporter) -> Runner:
    make_run_context(db_enabled=False)
    return Runner(
        reporters=[null_reporter],
    )


def test_spec_labels_are_bounded_and_keep_full_case_id():
    case_id = UUID("00000000-0000-0000-0000-000000000001")
    spec = TestSpec(
        locator=Locator(Path("test_sample.py"), "test_case"),
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
            locator=Locator(Path("test_sample.py"), "test_fast"),
            is_async=False,
            params=(),
            modifiers=(),
            tags=frozenset({"fast", "smoke"}),
        ),
        TestSpec(
            locator=Locator(Path("test_sample.py"), "test_slow"),
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

    plan = TestSpecCollector((), (), None).build_spec_collection(
        (tmp_path,), explicit_root=tmp_path
    )
    specs_by_name = {spec.full_name: spec.tags for spec in plan.specs}

    assert plan.suite_root == tmp_path
    assert [spec.collection_index for spec in plan.specs] == [0, 1, 2, 3]
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
        .build_spec_collection((tmp_path,))
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

    plan = TestSpecCollector([], [], "good").build_spec_collection(
        [str(tmp_path)]
    )
    items = TestLoader(plan.suite_root).load_from_collection(plan)

    assert [item.spec.locator.function_name for item in items] == ["test_good"]


def test_load_from_collection_skips_unselected_invalid_tests_in_same_module(
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

    plan = TestSpecCollector([], [], "good").build_spec_collection(
        [str(tmp_path)]
    )
    items = TestLoader(plan.suite_root).load_from_collection(plan)

    assert [item.spec.locator.function_name for item in items] == ["test_good"]


def test_load_from_collection_enriches_runtime_metadata(tmp_path):
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

    plan = TestSpecCollector((), (), None).build_spec_collection(
        (tmp_path / "test_metadata.py",)
    )
    planned_specs = {spec.locator.function_name: spec for spec in plan.specs}

    assert planned_specs["test_main_skip"].params == ()
    assert planned_specs["test_main_skip"].skip_reason is None
    assert planned_specs["test_main_skip"].modifiers == ()
    assert planned_specs["test_expected_failure"].xfail_reason is None
    valid_plan = replace(
        plan,
        specs=tuple(
            spec
            for spec in plan.specs
            if spec.locator.function_name
            in {"test_main_skip", "test_expected_failure"}
        ),
    )
    items = TestLoader(valid_plan.suite_root).load_from_collection(valid_plan)
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
        TestLoader(plan.suite_root).load_from_collection(plan)
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


def test_load_from_collection_raises_setup_failures(tmp_path):
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

    plan = TestSpecCollector((), (), None).build_spec_collection((tmp_path,))

    with pytest.raises(TestDefinitionErrors) as raised:
        TestLoader(plan.suite_root).load_from_collection(plan)

    [issue] = raised.value.exceptions
    assert issue.spec.full_name == "test_bad::test_bad"
    assert issue.message == "bad setup"


def test_load_from_collection_raises_missing_callable(tmp_path):
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

    original_plan = TestSpecCollector((), (), None).build_spec_collection(
        (tmp_path,)
    )
    bad_spec = replace(
        original_plan.specs[1],
        locator=Locator(
            module_path=original_plan.specs[1].locator.module_path,
            function_name="missing_test",
        ),
    )
    plan = replace(
        original_plan,
        specs=(original_plan.specs[0], bad_spec),
    )

    with pytest.raises(TestDefinitionErrors) as raised:
        TestLoader(plan.suite_root).load_from_collection(plan)

    [issue] = raised.value.exceptions
    assert issue.spec.locator.function_name == "missing_test"
    assert "missing_test" in issue.message


def test_load_from_collection_raises_non_callable_target(tmp_path):
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

    original_plan = TestSpecCollector((), (), None).build_spec_collection(
        (tmp_path,)
    )
    bad_spec = replace(
        original_plan.specs[0],
        locator=Locator(
            module_path=original_plan.specs[0].locator.module_path,
            function_name="not_callable",
        ),
    )
    plan = replace(original_plan, specs=(bad_spec,))

    with pytest.raises(TestDefinitionErrors) as raised:
        TestLoader(plan.suite_root).load_from_collection(plan)

    [issue] = raised.value.exceptions
    assert issue.spec.locator.function_name == "not_callable"
    assert "not a function or method" in issue.message


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

    run = await make_runner(null_reporter).run(
        items=materialize(tmp_path),
        resolver=ResourceResolver(registry),
    )

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

    plan = TestSpecCollector((), (), None).build_spec_collection(
        (tmp_path / "nested",)
    )
    [item] = TestLoader(plan.suite_root).load_from_collection(plan)

    assert item.suite_root == plan.suite_root
    assert item.setup_chain == plan.setup_chain_for(
        item.spec.locator.module_path
    )

    make_run_context(db_enabled=False)
    with TestContext(item=item, execution_id=uuid4()):
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

    plan = TestSpecCollector([], [], "good").build_spec_collection(
        [str(tmp_path)]
    )
    items = TestLoader(plan.suite_root).load_from_collection(plan)

    assert [item.spec.locator.function_name for item in items] == [
        "test_good",
        "test_good_two",
    ]
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

    run = await make_runner(null_reporter).run(
        items=materialize(tmp_path),
        resolver=ResourceResolver(registry),
    )

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
    execution_id = uuid4()
    graph = registry.compile_graph({execution_id: (item.spec, ("greeting",))})
    greeting = registry.definition(
        graph.injections_by_key[execution_id]["greeting"]
    )
    assert greeting.spec.scope == Scope.MODULE
