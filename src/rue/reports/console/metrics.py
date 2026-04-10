"""Renders the METRICS section at the end of a run."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from rue.resources import ResourceIdentity, Scope

from .shared import (
    format_assertion_result,
    format_label,
    oneline,
    safe_relative_path,
    truncate,
)

if TYPE_CHECKING:
    from uuid import UUID

    from rue.assertions import AssertionResult
    from rue.resources.metrics.base import MetricResult
    from rue.testing.models.result import TestExecution


_SCOPE_ORDER = {
    Scope.SESSION: 0,
    Scope.SUITE: 1,
    Scope.CASE: 2,
}
_LEADING_METRIC_VAR = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.(.+)$")


@dataclass(frozen=True, slots=True)
class MetricValue:
    value_str: str
    passed: int
    total: int
    has_failures: bool


@dataclass(slots=True)
class MetricGroup:
    key: ResourceIdentity
    metrics: list[MetricResult] = field(default_factory=list)
    display_name: str = ""

    @property
    def assertions(self) -> list[AssertionResult]:
        return [
            assertion
            for metric in self.metrics
            for assertion in metric.assertion_results
        ]

    @property
    def has_failures(self) -> bool:
        return any(metric.has_failures for metric in self.metrics)

    def contributors(self, attr: str) -> set[str]:
        values: set[str] = set()
        for metric in self.metrics:
            values.update(getattr(metric.metadata, attr))
        return values


class MetricsRenderer:
    def render(
        self,
        metric_results: list[MetricResult],
        verbosity: int,
        executions: list[TestExecution] | None = None,
    ) -> list[RenderableType]:
        if not metric_results:
            return []

        renderables: list[RenderableType] = [Rule("METRICS", characters="=")]
        groups = self._group_metrics(metric_results)
        if not groups:
            return renderables

        execution_lookup = self._execution_lookup(executions or [])
        group_lookup = {group.key: group for group in groups}
        parents_by_child, children_by_parent = self._group_graph(groups)

        if verbosity < 0:
            failed_count = sum(1 for group in groups if group.has_failures)
            if failed_count:
                renderables.append(
                    Text(f"{failed_count} failed metric groups", style="yellow")
                )
            return renderables

        renderables.append(self._section_header("OVERVIEW"))
        renderables.append(self._build_overview(groups))
        if verbosity == 0:
            return renderables

        detail_groups = [
            group
            for group in groups
            if self._is_interesting(
                group, parents_by_child, children_by_parent
            )
        ]
        if detail_groups:
            renderables.append(Text(""))
            renderables.append(self._section_header("BREAKDOWN"))
        for group in detail_groups:
            renderables.append(Text(""))
            renderables.append(
                self._build_detail_panel(
                    group,
                    execution_lookup,
                    group_lookup,
                    parents_by_child,
                    children_by_parent,
                )
            )
        return renderables

    def _group_metrics(self, metric_results: list[MetricResult]) -> list[MetricGroup]:
        grouped: dict[ResourceIdentity, MetricGroup] = {}
        for metric in metric_results:
            key = self._group_key(metric)
            group = grouped.setdefault(key, MetricGroup(key=key))
            group.metrics.append(metric)

        name_counts: dict[str, int] = {}
        for key in grouped:
            name_counts[key.name] = name_counts.get(key.name, 0) + 1

        groups = sorted(grouped.values(), key=self._group_sort_key)
        for group in groups:
            if name_counts[group.key.name] > 1:
                provider = self._provider_label(group.key)
                group.display_name = (
                    f"{group.key.name} @ {provider}" if provider else group.key.name
                )
            else:
                group.display_name = group.key.name
        return groups

    def _group_key(self, metric: MetricResult) -> ResourceIdentity:
        return metric.metadata.identity

    def _group_sort_key(self, group: MetricGroup) -> tuple[bool, int, str]:
        return (
            not group.has_failures,
            _SCOPE_ORDER.get(group.key.scope, 99),
            group.display_name or group.key.name,
        )

    def _group_graph(
        self, groups: list[MetricGroup]
    ) -> tuple[
        dict[ResourceIdentity, set[ResourceIdentity]],
        dict[ResourceIdentity, set[ResourceIdentity]],
    ]:
        parents_by_child: dict[ResourceIdentity, set[ResourceIdentity]] = {}
        children_by_parent: dict[ResourceIdentity, set[ResourceIdentity]] = {}
        group_lookup = {group.key: group for group in groups}

        for group in groups:
            for metric in group.metrics:
                for dependency in metric.dependencies:
                    if dependency not in group_lookup:
                        continue
                    parents_by_child.setdefault(group.key, set()).add(
                        dependency
                    )
                    children_by_parent.setdefault(dependency, set()).add(
                        group.key
                    )

        return parents_by_child, children_by_parent

    def _execution_lookup(
        self, executions: list[TestExecution]
    ) -> dict[UUID, TestExecution]:
        lookup: dict[UUID, TestExecution] = {}
        stack = list(executions)
        while stack:
            execution = stack.pop()
            lookup[execution.execution_id] = execution
            stack.extend(execution.sub_executions)
        return lookup

    def _evaluate(self, metric: MetricResult) -> MetricValue:
        value = metric.value
        value_str = (
            "N/A" if isinstance(value, float) and math.isnan(value) else str(value)
        )
        assertions = metric.assertion_results
        passed = sum(1 for assertion in assertions if assertion.passed)
        total = len(assertions)
        return MetricValue(
            value_str,
            passed,
            total,
            any(not assertion.passed for assertion in assertions),
        )

    def _build_overview(self, groups: list[MetricGroup]) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("Metric")
        table.add_column("Scope", no_wrap=True)
        table.add_column("Value", justify="right")
        table.add_column("Assertions")
        table.add_column("Contributors", no_wrap=True)

        for group in groups:
            table.add_row(
                group.display_name,
                self._scope_cell(group),
                self._group_value_summary(group),
                self._assertion_summary(group),
                self._contributor_counts(group),
            )

        return table

    def _scope_cell(self, group: MetricGroup) -> str:
        count = len(group.metrics)
        if count == 1:
            return group.key.scope.value
        return f"{group.key.scope.value} ×{count}"

    def _group_value_summary(self, group: MetricGroup) -> str:
        values = [self._evaluate(metric).value_str for metric in group.metrics]
        if len(values) == 1:
            return values[0]
        unique = list(dict.fromkeys(values))
        if len(unique) == 1:
            return f"{unique[0]} ×{len(values)}"
        if all(self._is_number(metric.value) for metric in group.metrics):
            floats = [float(metric.value) for metric in group.metrics]
            return f"{min(floats):g}..{max(floats):g}"
        return f"{len(values)} values"

    def _assertion_summary(self, group: MetricGroup) -> Text:
        if not group.assertions:
            return Text("")

        snippets: list[Text] = []
        seen: set[str] = set()
        for assertion in group.assertions:
            snippet = self._assertion_snippet(assertion)
            if snippet.plain in seen:
                continue
            seen.add(snippet.plain)
            snippets.append(snippet)

        summary = Text()
        for index, snippet in enumerate(snippets[:2]):
            if index:
                summary.append(", ", style="dim")
            summary.append_text(snippet)
        if len(snippets) > 2:
            summary.append(f" +{len(snippets) - 2}", style="dim")
        summary.truncate(56, overflow="ellipsis")
        return summary

    def _assertion_snippet(self, assertion: AssertionResult) -> Text:
        expr = oneline(assertion.expression_repr.expr)
        if expr.startswith("assert "):
            expr = expr[7:]
        expr = self._normalize_metric_expr(expr)

        style = "red" if not assertion.passed else "green"
        resolved_args = [
            (
                self._normalize_metric_expr(oneline(label)),
                oneline(value),
            )
            for label, value in assertion.expression_repr.resolved_args.items()
        ]
        resolved_args = [
            (label, value)
            for label, value in resolved_args
            if label
        ]
        resolved_args.sort(key=lambda item: len(item[0]), reverse=True)

        snippet = Text()
        index = 0
        while index < len(expr):
            match = next(
                (
                    (label, value)
                    for label, value in resolved_args
                    if expr.startswith(label, index)
                ),
                None,
            )
            if match is None:
                snippet.append(expr[index], style=style)
                index += 1
                continue

            label, value = match
            snippet.append(label, style="grey62")
            snippet.append(" / ", style="dim")
            snippet.append(value)
            index += len(label)

        return snippet

    def _contributor_counts(self, group: MetricGroup) -> Text:
        text = Text()
        counts = [
            ("M", len(group.contributors("collected_from_modules"))),
            ("T", len(group.contributors("collected_from_tests"))),
            ("R", len(group.contributors("collected_from_resources"))),
            ("C", len(group.contributors("collected_from_cases"))),
        ]
        for index, (label, count) in enumerate(counts):
            if index:
                text.append(" ")
            text.append(label, style="bold")
            text.append(str(count), style="dim")
        return text

    def _is_interesting(
        self,
        group: MetricGroup,
        parents_by_child: dict[ResourceIdentity, set[ResourceIdentity]],
        children_by_parent: dict[ResourceIdentity, set[ResourceIdentity]],
    ) -> bool:
        return (
            group.has_failures
            or len(group.metrics) > 1
            or len(group.contributors("collected_from_modules")) > 1
            or len(group.contributors("collected_from_resources")) > 1
            or group.key in parents_by_child
            or group.key in children_by_parent
        )

    def _build_detail_panel(
        self,
        group: MetricGroup,
        execution_lookup: dict[UUID, TestExecution],
        group_lookup: dict[ResourceIdentity, MetricGroup],
        parents_by_child: dict[ResourceIdentity, set[ResourceIdentity]],
        children_by_parent: dict[ResourceIdentity, set[ResourceIdentity]],
    ) -> Panel:
        renderables: list[RenderableType] = [self._build_summary_grid(group)]

        composite = self._build_composite_section(
            group,
            group_lookup,
            parents_by_child,
            children_by_parent,
        )
        if composite is not None:
            self._append_section(
                renderables,
                "Hierarchy",
                composite,
                inline=True,
            )

        contributors = self._build_contributors_grid(group)
        if contributors is not None:
            self._append_section(
                renderables,
                "Contributors",
                contributors,
                inline=True,
            )

        self._append_section(
            renderables,
            "Instances",
            self._build_instances_table(group, execution_lookup),
        )

        assertions = self._build_assertions_group(group, execution_lookup)
        if assertions is not None:
            self._append_section(renderables, "Assertions", assertions)

        border_style = "red" if group.has_failures else "cyan"
        return Panel(
            Group(*renderables),
            title=group.display_name,
            title_align="left",
            border_style=border_style,
            expand=True,
            padding=(1, 1),
        )

    def _build_summary_grid(self, group: MetricGroup) -> Table:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold", no_wrap=True)
        table.add_column()
        table.add_row("Scope", group.key.scope.value)
        table.add_row("Instances", str(len(group.metrics)))
        table.add_row("Value", self._group_value_summary(group))

        provider = self._provider_label(group.key)
        if provider:
            table.add_row("Path", provider)

        return table

    def _append_section(
        self,
        renderables: list[RenderableType],
        title: str,
        body: RenderableType,
        *,
        inline: bool = False,
    ) -> None:
        renderables.append(Text(""))
        if inline:
            renderables.append(self._inline_section(title, body))
            return
        renderables.extend([self._section_header(title), body])

    def _section_header(self, title: str) -> Text:
        return Text(title, style="bold cyan")

    def _inline_section(self, title: str, body: RenderableType) -> Table:
        table = Table.grid(expand=False, padding=(0, 2))
        table.add_column(no_wrap=True, style="bold cyan")
        table.add_column()
        table.add_row(title, body)
        return table

    def _build_composite_section(
        self,
        group: MetricGroup,
        group_lookup: dict[ResourceIdentity, MetricGroup],
        parents_by_child: dict[ResourceIdentity, set[ResourceIdentity]],
        children_by_parent: dict[ResourceIdentity, set[ResourceIdentity]],
    ) -> RenderableType | None:
        if group.key not in parents_by_child and group.key not in children_by_parent:
            return None

        roots = parents_by_child.get(group.key, set())
        if len(roots) == 1:
            root = next(iter(roots))
            while len(parents_by_child.get(root, set())) == 1:
                parent = next(iter(parents_by_child[root]))
                if parent == root:
                    break
                root = parent
        else:
            root = group.key

        tree = Tree(self._tree_label(group_lookup[root], current=group.key == root))
        self._add_tree_children(
            tree,
            root,
            group.key,
            group_lookup,
            children_by_parent,
            seen={root},
        )
        return tree

    def _add_tree_children(
        self,
        tree: Tree,
        key: ResourceIdentity,
        current: ResourceIdentity,
        group_lookup: dict[ResourceIdentity, MetricGroup],
        children_by_parent: dict[ResourceIdentity, set[ResourceIdentity]],
        seen: set[ResourceIdentity],
    ) -> None:
        for child in sorted(
            children_by_parent.get(key, set()),
            key=lambda item: group_lookup[item].display_name,
        ):
            child_group = group_lookup[child]
            node = tree.add(
                self._tree_label(child_group, current=child == current)
            )
            if child in seen:
                continue
            self._add_tree_children(
                node,
                child,
                current,
                group_lookup,
                children_by_parent,
                seen={*seen, child},
            )

    def _tree_label(self, group: MetricGroup, *, current: bool) -> Text:
        text = Text(group.display_name, style="bold" if current else "")
        if group.key.scope:
            text.append(f" [{group.key.scope.value}]", style="dim")
        return text

    def _build_contributors_grid(self, group: MetricGroup) -> Table | None:
        rows = [
            ("Modules", self._render_values(group.contributors("collected_from_modules"), path=True)),
            ("Tests", self._render_values(group.contributors("collected_from_tests"))),
            ("Resources", self._render_values(group.contributors("collected_from_resources"))),
            ("Cases", self._render_values(group.contributors("collected_from_cases"), case=True)),
        ]
        rows = [(label, value) for label, value in rows if value]
        if not rows:
            return None

        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold", no_wrap=True)
        table.add_column()
        for label, value in rows:
            table.add_row(label, value)
        return table

    def _build_instances_table(
        self,
        group: MetricGroup,
        execution_lookup: dict[UUID, TestExecution],
    ) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("Suffix", no_wrap=True)
        table.add_column("Module")
        table.add_column("Tests")
        table.add_column("Value", justify="right")
        table.add_column("Assertions")

        for metric in sorted(group.metrics, key=self._metric_sort_key):
            mv = self._evaluate(metric)
            table.add_row(
                self._instance_label(metric, execution_lookup),
                self._render_values(
                    metric.metadata.collected_from_modules, path=True
                )
                or "—",
                self._render_values(metric.metadata.collected_from_tests) or "—",
                mv.value_str,
                self._instance_assertions(metric),
            )
        return table

    def _build_assertions_group(
        self,
        group: MetricGroup,
        execution_lookup: dict[UUID, TestExecution],
    ) -> Group | None:
        blocks: list[RenderableType] = []
        show_instance = len(group.metrics) > 1

        for metric in sorted(group.metrics, key=self._metric_sort_key):
            instance = self._instance_label(metric, execution_lookup)
            for assertion in metric.assertion_results:
                heading = (
                    f"Metric Assertion {instance}"
                    if show_instance
                    else "Metric Assertion"
                )
                if blocks:
                    blocks.append(Text(""))
                blocks.append(
                    format_assertion_result(assertion, heading=heading)
                )

        return Group(*blocks) if blocks else None

    def _metric_sort_key(self, metric: MetricResult) -> tuple[str, str]:
        return (
            metric.primary_case_id,
            self._provider_label(metric.metadata.identity) or "",
        )

    def _instance_label(
        self,
        metric: MetricResult,
        execution_lookup: dict[UUID, TestExecution],
    ) -> str:
        case_id = metric.primary_case_id
        if case_id:
            return format_label(case_id)
        if metric.execution_id is not None:
            return str(metric.execution_id)[:8]
        provider = self._provider_label(metric.metadata.identity)
        return truncate(provider or "metric", 28)

    def _instance_assertions(self, metric: MetricResult) -> Text:
        mv = self._evaluate(metric)
        if not mv.total:
            return Text("")
        snippet = self._assertion_summary(MetricGroup(self._group_key(metric), [metric]))
        if snippet.plain:
            return snippet
        style = "red" if mv.has_failures else "green"
        return Text(f"{mv.passed}/{mv.total}", style=style)

    def _provider_label(self, key: ResourceIdentity) -> str | None:
        return self._path_label(key.provider_path or key.provider_dir)

    def _normalize_metric_expr(self, expr: str) -> str:
        if "." not in expr:
            return expr
        prefix, rest = expr.split(".", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", prefix):
            return rest
        return expr

    def _path_label(self, path_str: str | None) -> str | None:
        if not path_str:
            return None
        return safe_relative_path(Path(path_str)).as_posix()

    def _render_values(
        self,
        values: set[str],
        *,
        path: bool = False,
        case: bool = False,
        limit: int = 4,
    ) -> str:
        if not values:
            return ""
        items = sorted(values)
        if path:
            items = [self._path_label(item) or item for item in items]
        if case:
            items = [format_label(item) for item in items]
        rendered = ", ".join(items[:limit])
        if len(items) > limit:
            rendered += f" +{len(items) - limit}"
        return rendered

    @staticmethod
    def _is_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
