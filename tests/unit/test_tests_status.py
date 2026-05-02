from pathlib import Path
from textwrap import dedent
from uuid import UUID

import pytest
from rich.console import Console

from rue.cli.tests.status import (
    StatusNode,
    StatusRenderer,
    TestsStatusBuilder,
    TestsStatusReport,
)
from rue.config import Config
from rue.models import Locator
from rue.resources import Scope
from rue.resources.models import ResourceSpec
from rue.testing.discovery import TestDefinitionErrors, TestSpecCollector
from rue.testing.execution.base import ExecutionBackend
from rue.testing.models import TestStatus
from rue.testing.models.modifiers import IterateModifier
from tests.helpers import make_definition


def write_files(root: Path, files: dict[str, str]) -> None:
    for relative_path, source in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(source))


def build_report(path: Path) -> TestsStatusReport:
    collection = TestSpecCollector((), (), None).build_spec_collection((path,))
    builder = TestsStatusBuilder(Config.model_construct())
    return builder.build(collection, store=None)


def test_status_builder_matches_execution_tree_shape(tmp_path):
    write_files(
        tmp_path,
        {
            "test_status_tree.py": """
                import rue
                from rue.testing import Case, CaseGroup

                @rue.test
                def test_plain():
                    pass

                @rue.test.backend("main")
                @rue.test.iterate(2)
                def test_repeat():
                    pass

                @rue.test.iterate.params("value", [1, 2], ids=["one", "two"])
                def test_params(value):
                    pass

                @rue.test.iterate.cases(
                    Case(metadata={"slug": "one"}),
                    Case(metadata={"slug": "two"}),
                )
                def test_cases(case):
                    pass

                @rue.test.iterate.groups(
                    CaseGroup(
                        name="alpha",
                        cases=[
                            Case(metadata={"slug": "a"}),
                            Case(metadata={"slug": "b"}),
                        ],
                    ),
                    CaseGroup(
                        name="beta",
                        cases=[Case(metadata={"slug": "c"})],
                    ),
                )
                def test_groups(group, case):
                    pass
            """
        },
    )

    report = build_report(tmp_path / "test_status_tree.py")
    [module_path] = report.module_nodes
    nodes = {
        node.definition.spec.full_name: node
        for node in report.module_nodes[module_path]
    }

    assert nodes["test_status_tree::test_plain"].leaf_count == 1
    assert (
        nodes["test_status_tree::test_repeat"].backend
        is ExecutionBackend.MAIN
    )
    assert len(nodes["test_status_tree::test_repeat"].children) == 2
    assert nodes["test_status_tree::test_params"].leaf_count == 2
    assert len(nodes["test_status_tree::test_params"].children) == 2
    assert (
        nodes["test_status_tree::test_params"]
        .children[0]
        .definition.spec.suffix
        == "one"
    )
    assert nodes["test_status_tree::test_cases"].leaf_count == 2
    assert (
        nodes["test_status_tree::test_cases"].children[0].definition.spec.suffix
        == "{'slug': 'one'}"
    )
    assert nodes["test_status_tree::test_groups"].leaf_count == 3
    assert len(nodes["test_status_tree::test_groups"].children[0].children) == 2


def test_status_builder_raises_definition_errors(tmp_path):
    write_files(
        tmp_path,
        {
            "test_definition.py": """
                from rue import test

                @test.iterate.params("value", [])
                def test_definition(value):
                    pass
            """,
        },
    )

    collection = TestSpecCollector((), (), None).build_spec_collection(
        (tmp_path,)
    )
    builder = TestsStatusBuilder(Config.model_construct())
    with pytest.raises(TestDefinitionErrors) as raised:
        builder.build(collection, store=None)

    [issue] = raised.value.exceptions
    assert "requires at least one value set" in issue.message


def test_status_builder_reports_resolve_issues(tmp_path):
    write_files(
        tmp_path,
        {
            "test_unknown.py": """
                import rue

                @rue.test
                def test_unknown(missing_resource):
                    pass
            """,
            "test_sut.py": """
                import rue
                from rue.resources.sut import sut

                @sut
                def broken():
                    return 1

                @rue.test
                def test_sut(broken):
                    pass
            """,
        },
    )

    report = build_report(tmp_path)
    nodes = {
        node.definition.spec.full_name: node
        for module_nodes in report.module_nodes.values()
        for node in module_nodes
    }

    assert any(
        issue.phase == "resolve"
        and "Unknown resource: missing_resource" in issue.message
        for issue in nodes["test_unknown::test_unknown"].issues
    )
    assert any(
        issue.phase == "resolve"
        and "@sut factories must return or yield a SUT." in issue.message
        for issue in nodes["test_sut::test_sut"].issues
    )


def test_status_builder_reports_circular_resource_dependencies(tmp_path):
    write_files(
        tmp_path,
        {
            "test_cycle.py": """
                import rue

                @rue.resource
                def first(second):
                    return 1

                @rue.resource
                def second(first):
                    return 2

                @rue.test
                def test_cycle(first):
                    pass
            """
        },
    )

    report = build_report(tmp_path / "test_cycle.py")
    [node] = next(iter(report.module_nodes.values()))
    assert any(
        issue.phase == "resolve"
        and "Circular resource dependency detected" in issue.message
        for issue in node.issues
    )


def test_status_builder_groups_resources_by_runtime_type(tmp_path):
    write_files(
        tmp_path,
        {
            "test_types.py": """
                import rue

                @rue.resource
                def db():
                    return 1

                @rue.metric
                def latency():
                    yield rue.Metric()

                @rue.sut
                def agent():
                    return rue.SUT(lambda: "ok")

                @rue.test
                def test_types(db, latency, agent):
                    pass
            """
        },
    )

    report = build_report(tmp_path / "test_types.py")
    [node] = next(iter(report.module_nodes.values()))

    assert set(node.resources_by_type) == {"int", "Metric", "SUT"}
    assert [
        spec.locator.function_name for spec in node.resources_by_type["int"]
    ] == ["db"]
    assert [
        spec.locator.function_name
        for spec in node.resources_by_type["Metric"]
    ] == ["latency"]
    assert [
        spec.locator.function_name for spec in node.resources_by_type["SUT"]
    ] == ["agent"]


def test_status_renderer_respects_verbosity_levels():
    child_one = StatusNode(
        definition=make_definition(
            "test_tree",
            suffix="one",
            case_id=UUID("00000000-0000-0000-0000-000000000001"),
        ),
        backend=ExecutionBackend.ASYNCIO,
        history=(TestStatus.PASSED, TestStatus.FAILED),
        resources_by_type={
            "Metric": (
                ResourceSpec(
                    locator=Locator(
                        module_path=Path("/tmp/project/confrue_metrics.py"),
                        function_name="latency",
                    ),
                    scope=Scope.RUN,
                ),
            ),
            "SUT": (
                ResourceSpec(
                    locator=Locator(
                        module_path=Path("/tmp/project/conftest.py"),
                        function_name="agent",
                    ),
                    scope=Scope.TEST,
                ),
            ),
        },
    )
    child_two = StatusNode(
        definition=make_definition("test_tree", suffix="two"),
        backend=ExecutionBackend.ASYNCIO,
        history=(TestStatus.PASSED, None),
    )
    root = StatusNode(
        definition=make_definition(
            "test_tree",
            modifiers=(IterateModifier(count=2, min_passes=1),),
        ),
        backend=ExecutionBackend.ASYNCIO,
        history=(TestStatus.PASSED, None),
        children=(child_one, child_two),
        leaf_count=2,
    )
    report = TestsStatusReport(
        module_nodes={Path("tests/test_tree.py"): [root]},
    )
    renderer = StatusRenderer()

    compact = Console(record=True, width=140)
    compact.print(renderer.render(report, 0))
    compact_text = compact.export_text()
    assert "2 variations" in compact_text
    assert "Metric" not in compact_text
    assert "History" not in compact_text
    assert "test_module::test_tree" not in compact_text

    verbose = Console(record=True, width=140)
    verbose.print(renderer.render(report, 1))
    verbose_text = verbose.export_text()
    assert "[one]" in verbose_text
    assert "[two]" in verbose_text
    assert "x 2 iterations" in verbose_text
    assert "[backend: asyncio]" in verbose_text
    assert verbose_text.count("[backend: asyncio]") == 2
    assert "History" not in verbose_text
    assert "00000000-0000-0000-0000-000000000001" not in verbose_text

    very_verbose = Console(record=True, width=140)
    very_verbose.print(renderer.render(report, 2))
    very_verbose_text = very_verbose.export_text()
    assert "History" in very_verbose_text
    assert "✓✗" in very_verbose_text
    assert "[one | 00000000-0000-0000-0000-000000000001]" in very_verbose_text
    assert "Metric" in very_verbose_text
    assert "SUT" in very_verbose_text
    assert "confrue_metrics.py" in very_verbose_text
    assert "00000000-0000-0000-0000-000000000001" in very_verbose_text
