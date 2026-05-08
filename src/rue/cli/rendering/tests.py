"""Shared test report models and tree rendering."""

# ruff: noqa: D102

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from rue.cli.rendering.primitives import STATUS_STYLES, safe_relative_path
from rue.resources import ResourceSpec
from rue.testing.execution.backend import ExecutionBackend
from rue.testing.execution.models import LoadedTestDef, TestStatus
from rue.testing.execution.suite.models import ExecutedSuite


_BACKEND_STYLE = "dim blue"
_MODIFIER_STYLE = "blue"
_RESOURCE_SCOPE_STYLE = "dim blue"
_RESOURCE_TYPE_STYLE = "bold magenta"
_TREE_MODULE_STYLE = "medium_purple"
_COMPACT_MODULE_STYLE = "white"


@dataclass(frozen=True)
class TestReportIssue:
    """Issue attached to a rendered test node."""

    phase: str
    message: str


@dataclass(frozen=True)
class TestReportNode:
    """Rendered test tree node."""

    definition: LoadedTestDef
    backend: ExecutionBackend | None
    history: tuple[TestStatus | None, ...] = ()
    issues: tuple[TestReportIssue, ...] = ()
    resources_by_type: dict[str, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    children: tuple[TestReportNode, ...] = ()
    leaf_count: int = 1


@dataclass(frozen=True)
class TestReport:
    """Rendered test report grouped by module."""

    suite_window: tuple[ExecutedSuite, ...] = ()
    module_nodes: dict[Path, list[TestReportNode]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TestModuleView:
    """Module label shared by suite and status output."""

    path: Path

    def compact_text(self) -> Text:
        return Text(f" • {self.label} ", style=_COMPACT_MODULE_STYLE)

    def tree_text(self) -> Text:
        return Text(f"• {self.label} ", style=_TREE_MODULE_STYLE)

    @property
    def label(self) -> str:
        return safe_relative_path(self.path).as_posix()


class TestTreeRenderer:
    """Render grouped test reports as Rich trees."""

    __test__ = False

    def render(
        self,
        report: TestReport,
        verbosity: int,
    ) -> RenderableType:
        parts: list[RenderableType] = [self.summary(report, verbosity)]
        for module_path, nodes in sorted(
            report.module_nodes.items(),
            key=lambda item: TestModuleView(item[0]).label,
        ):
            tree = Tree(TestModuleView(module_path).tree_text())
            for node in nodes:
                self.add_node(tree, node, verbosity, top_level=True)
            parts.append(tree)
        return Group(*parts)

    def summary(self, report: TestReport, verbosity: int) -> Panel:
        """Render aggregate module, root, collected, and issue counts."""
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim")
        table.add_column()
        roots = sum(len(nodes) for nodes in report.module_nodes.values())
        collected = sum(
            node.leaf_count
            for nodes in report.module_nodes.values()
            for node in nodes
        )
        issues = sum(
            self.issue_count(node)
            for nodes in report.module_nodes.values()
            for node in nodes
        )
        table.add_row(
            "Modules",
            Text(str(len(report.module_nodes)), style="bold"),
        )
        table.add_row("Roots", Text(str(roots), style="bold"))
        table.add_row("Collected", Text(str(collected), style="bold"))
        table.add_row(
            "Issues",
            Text(str(issues), style="bold yellow" if issues else "dim"),
        )
        if verbosity >= 2:
            history_available = report.suite_window or any(
                node.history
                for nodes in report.module_nodes.values()
                for node in nodes
            )
            if history_available:
                history_text = Text()
                history_text.append(
                    str(len(report.suite_window)),
                    style="bold",
                )
                history_text.append(" recorded suite(s)", style="dim")
            else:
                history_text = Text("Unavailable", style="dim")
            table.add_row("History", history_text)
        return Panel(
            table,
            title=Text("Test Status", style="bold cyan"),
            border_style="yellow" if issues else "cyan",
        )

    def add_node(
        self,
        parent: Tree,
        node: TestReportNode,
        verbosity: int,
        *,
        top_level: bool = False,
    ) -> None:
        """Append one report node and any visible children to a Rich tree."""
        branch = parent.add(
            self.node_text(node, verbosity, top_level=top_level)
        )
        if verbosity == 0 and node.children:
            # Compact status keeps parameterized children summarized.
            return

        for issue in node.issues:
            branch.add(self.issue_text(issue))

        if verbosity >= 2 and not node.children:
            for type_name, resources in sorted(node.resources_by_type.items()):
                group = branch.add(
                    Text(
                        f"[injected {type_name}]",
                        style=_RESOURCE_TYPE_STYLE,
                    )
                )
                for resource in resources:
                    group.add(self.resource_text(resource))

        for child in node.children:
            self.add_node(branch, child, verbosity)

    def node_text(
        self,
        node: TestReportNode,
        verbosity: int,
        *,
        top_level: bool,
    ) -> Text:
        """Render the label and inline metadata for one test tree node."""
        spec = node.definition.spec
        text = Text()
        if top_level:
            text.append_text(self.test_name_text(spec.local_name))
        else:
            text.append_text(
                self.case_label_text(spec.get_label(full=verbosity >= 2))
            )
        if node.children and spec.modifiers:
            summary = spec.modifiers[0].display_summary
            if summary:
                text.append(f" {summary}", style=_MODIFIER_STYLE)
        if not node.children and node.backend is not None:
            text.append(
                f" [backend: {node.backend.value}]",
                style=_BACKEND_STYLE,
            )
        if node.children and verbosity == 0:
            text.append(f" ({node.leaf_count} variations)", style="dim")
        issue_count = (
            self.issue_count(node) if verbosity == 0 else len(node.issues)
        )
        if issue_count:
            text.append(f" {issue_count} issue(s)", style="bold yellow")
        if verbosity >= 2 and node.history:
            text.append_text(self.history_text(node.history))
        return text

    def history_text(self, history: tuple[TestStatus | None, ...]) -> Text:
        """Render compact historical status symbols."""
        text = Text("  ", style="dim")
        for status in history:
            if status is None:
                text.append("·", style="dim")
                continue
            style = STATUS_STYLES[status]
            text.append(style.symbol, style=style.color)
        return text

    def issue_text(self, issue: TestReportIssue) -> Text:
        text = Text()
        text.append(f"{issue.phase}: ", style="bold yellow")
        text.append(issue.message, style="yellow")
        return text

    def resource_text(self, spec: ResourceSpec) -> Text:
        text = Text()
        text.append(spec.locator.function_name)
        text.append(
            f" [scope: {spec.scope.value}]",
            style=_RESOURCE_SCOPE_STYLE,
        )
        origin = spec.locator.module_path
        if origin:
            text.append(
                f" @ {safe_relative_path(origin).as_posix()}",
                style="dim",
            )
        return text

    def issue_count(self, node: TestReportNode) -> int:
        return len(node.issues) + sum(
            self.issue_count(child) for child in node.children
        )

    @staticmethod
    def test_name_text(name: str) -> Text:
        text = Text()
        if "::" in name:
            prefix, _, func = name.rpartition("::")
            text.append(f"{prefix}::", style="dim")
            text.append(func, style="bold")
        else:
            text.append(name, style="bold")
        return text

    @staticmethod
    def case_label_text(label: str | None) -> Text:
        label = label or "case"
        if label.startswith("[") and label.endswith("]"):
            return Text(label)
        text = Text()
        text.append("[", style="dim")
        text.append(label)
        text.append("]", style="dim")
        return text


__all__ = [
    "TestModuleView",
    "TestReport",
    "TestReportIssue",
    "TestReportNode",
    "TestTreeRenderer",
]
