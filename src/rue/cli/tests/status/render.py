"""Rich rendering for `rue tests status`."""

from __future__ import annotations

from pathlib import Path

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from rue.resources import ResourceSpec
from rue.testing.models import TestStatus

from rue.cli.tests.status.models import StatusIssue, StatusNode, TestsStatusReport


_STATUS_STYLES: dict[TestStatus, tuple[str, str]] = {
    TestStatus.PASSED: ("✓", "green"),
    TestStatus.FAILED: ("✗", "red"),
    TestStatus.ERROR: ("!", "yellow"),
    TestStatus.SKIPPED: ("-", "yellow"),
    TestStatus.XFAILED: ("x", "blue"),
    TestStatus.XPASSED: ("!", "magenta"),
}


class StatusRenderer:
    def render(
        self,
        report: TestsStatusReport,
        verbosity: int,
    ) -> RenderableType:
        parts: list[RenderableType] = [self._summary(report)]
        for module_path, nodes in sorted(report.module_nodes.items()):
            root_label = Text(f"• {_safe_relative_path(module_path).as_posix()}", style="bold")
            tree = Tree(root_label)
            for node in nodes:
                self._add_node(tree, node, verbosity, top_level=True)
            parts.append(tree)
        return Group(*parts)

    def _summary(self, report: TestsStatusReport) -> Panel:
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
            self._issue_count(node)
            for nodes in report.module_nodes.values()
            for node in nodes
        )
        history_available = report.run_window or any(
            node.history
            for nodes in report.module_nodes.values()
            for node in nodes
        )
        table.add_row(
            "Modules",
            Text(str(len(report.module_nodes)), style="bold"),
        )
        table.add_row("Roots", Text(str(roots), style="bold"))
        table.add_row("Collected", Text(str(collected), style="bold"))
        issues_text = Text(
            str(issues), style="bold yellow" if issues else "dim"
        )
        table.add_row("Issues", issues_text)
        if history_available:
            history_text = Text()
            history_text.append(
                str(len(report.run_window)), style="bold"
            )
            history_text.append(" recorded run(s)", style="dim")
        else:
            history_text = Text("Unavailable", style="dim")
        table.add_row("History", history_text)
        border_style = "yellow" if issues else "cyan"
        return Panel(
            table,
            title=Text("Test Status", style="bold cyan"),
            border_style=border_style,
        )

    def _add_node(
        self,
        parent: Tree,
        node: StatusNode,
        verbosity: int,
        *,
        top_level: bool = False,
    ) -> None:
        branch = parent.add(self._node_text(node, verbosity, top_level=top_level))
        if verbosity == 0 and node.children:
            return

        for issue in node.issues:
            branch.add(self._issue_text(issue))

        if verbosity >= 2 and not node.children:
            for type_name, resources in sorted(node.resources_by_type.items()):
                group = branch.add(Text(type_name, style="italic dim"))
                for resource in resources:
                    group.add(self._resource_text(resource))

        for child in node.children:
            self._add_node(branch, child, verbosity)

    def _node_text(
        self,
        node: StatusNode,
        verbosity: int,
        *,
        top_level: bool,
    ) -> Text:
        spec = node.definition.spec
        text = Text()
        if top_level:
            full = spec.full_name
            if "::" in full:
                prefix, _, func = full.rpartition("::")
                text.append(f"{prefix}::", style="dim")
                text.append(func, style="bold")
            else:
                text.append(full, style="bold")
        else:
            text.append("[", style="dim")
            text.append(spec.label or "case")
            text.append("]", style="dim")
        if node.children and spec.modifiers:
            text.append(f" [{spec.modifiers[0].display_name}]", style="dim")
        if node.backend is not None:
            text.append(f" [{node.backend.value}]", style="dim")
        if node.children and verbosity == 0:
            text.append(f" ({node.leaf_count} variations)", style="dim")
        issue_count = self._issue_count(node) if verbosity == 0 else len(node.issues)
        if issue_count:
            text.append(f" {issue_count} issue(s)", style="bold yellow")
        if node.history:
            text.append_text(self._history_text(node.history))
        return text

    def _history_text(self, history: tuple[TestStatus | None, ...]) -> Text:
        text = Text("  ", style="dim")
        for status in history:
            if status is None:
                text.append("·", style="dim")
            else:
                symbol, color = _STATUS_STYLES[status]
                text.append(symbol, style=color)
        return text

    def _issue_text(self, issue: StatusIssue) -> Text:
        text = Text()
        text.append(f"{issue.phase}: ", style="bold yellow")
        text.append(issue.message, style="yellow")
        return text

    def _resource_text(self, spec: ResourceSpec) -> Text:
        text = Text()
        text.append(spec.name, style="bold")
        text.append(f" [{spec.scope.value}]", style="dim")
        origin = spec.provider_path or spec.provider_dir
        if origin:
            text.append(
                f" @ {_safe_relative_path(Path(origin)).as_posix()}",
                style="dim",
            )
        return text

    def _issue_count(self, node: StatusNode) -> int:
        return len(node.issues) + sum(
            self._issue_count(child) for child in node.children
        )


def _safe_relative_path(path: Path) -> Path:
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


__all__ = ["StatusRenderer"]
