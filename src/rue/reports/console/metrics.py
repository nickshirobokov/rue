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

from rue.models import Spec
from rue.resources import ResourceSpec, Scope

from .shared import (
    format_assertion_result,
    oneline,
    safe_relative_path,
    truncate,
)


if TYPE_CHECKING:
    from rue.assertions import AssertionResult
    from rue.resources.metrics.base import MetricResult
    from rue.testing.models.executed import ExecutedTest


_SCOPE_ORDER = {
    Scope.RUN: 0,
    Scope.MODULE: 1,
    Scope.TEST: 2,
}
_METRIC_PREFIX_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class MetricValue:
    value_str: str
    passed: int
    total: int
    has_failures: bool

    @classmethod
    def from_result(cls, metric: MetricResult) -> MetricValue:
        value = metric.value
        value_str = (
            "N/A"
            if isinstance(value, float) and math.isnan(value)
            else str(value)
        )
        assertions = metric.assertion_results
        passed = sum(1 for a in assertions if a.passed)
        return cls(
            value_str,
            passed,
            len(assertions),
            any(not a.passed for a in assertions),
        )


@dataclass(slots=True)
class MetricGroup:
    key: ResourceSpec
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

    def is_interesting(
        self,
        parents: dict[ResourceSpec, set[ResourceSpec]],
        children: dict[ResourceSpec, set[ResourceSpec]],
    ) -> bool:
        return (
            self.has_failures
            or len(self.metrics) > 1
            or len(self.consumer_modules()) > 1
            or len(self.resource_consumers()) > 1
            or self.key in parents
            or self.key in children
        )

    def consumers(self) -> list[Spec]:
        values: list[Spec] = []
        for metric in self.metrics:
            values.extend(metric.metadata.consumers)
        return values

    def consumer_modules(self) -> set[str]:
        return self._consumer_modules(self.consumers())

    def test_consumers(self) -> set[str]:
        return self._test_consumers(self.consumers())

    def resource_consumers(self) -> set[str]:
        return self._resource_consumers(self.consumers())

    def consumer_cases(self) -> set[str]:
        return self._consumer_cases(self.consumers())

    @staticmethod
    def _consumer_modules(consumers: list[Spec]) -> set[str]:
        return {
            str(consumer.locator.module_path)
            for consumer in consumers
            if consumer.locator.module_path is not None
        }

    @staticmethod
    def _test_consumers(consumers: list[Spec]) -> set[str]:
        return {
            consumer.locator.function_name
            for consumer in consumers
            if not isinstance(consumer, ResourceSpec)
        }

    @staticmethod
    def _resource_consumers(consumers: list[Spec]) -> set[str]:
        return {
            consumer.locator.function_name
            for consumer in consumers
            if isinstance(consumer, ResourceSpec)
        }

    @staticmethod
    def _consumer_cases(consumers: list[Spec]) -> set[str]:
        cases = {
            str(case_id)
            for consumer in consumers
            if (case_id := getattr(consumer, "case_id", None)) is not None
        }
        cases.update(
            suffix
            for consumer in consumers
            if (suffix := getattr(consumer, "suffix", None))
        )
        return cases

    def value_summary(self) -> str:
        values = [MetricValue.from_result(m).value_str for m in self.metrics]
        match values:
            case [single]:
                return single
            case _ if len(set(values)) == 1:
                return f"{values[0]} ×{len(values)}"
            case _ if all(
                isinstance(m.value, (int, float))
                and not isinstance(m.value, bool)
                for m in self.metrics
            ):
                floats = [float(m.value) for m in self.metrics]  # type: ignore
                return f"{min(floats):g}..{max(floats):g}"
            case _:
                return f"{len(values)} values"


class MetricsRenderer:
    def __init__(self) -> None:
        self._groups: list[MetricGroup] = []
        self._group_lookup: dict[ResourceSpec, MetricGroup] = {}
        self._parents: dict[ResourceSpec, set[ResourceSpec]] = {}
        self._children: dict[ResourceSpec, set[ResourceSpec]] = {}

    def render(
        self,
        metric_results: list[MetricResult],
        verbosity: int,
        executions: list[ExecutedTest] | None = None,
    ) -> list[RenderableType]:
        if not metric_results:
            return []

        self._groups = self._build_groups(metric_results)
        self._group_lookup = {g.key: g for g in self._groups}
        _ = executions
        self._parents, self._children = self._build_relationships()

        renderables: list[RenderableType] = [
            Rule(Text("METRICS", style="bold cyan"), characters="=")
        ]
        if not self._groups:
            return renderables

        match verbosity:
            case -1:
                self._add_minimal(renderables)
            case 0:
                self._add_overview(renderables)
            case _:
                self._add_overview(renderables)
                self._add_breakdown(renderables)

        return renderables

    def _build_groups(
        self, metric_results: list[MetricResult]
    ) -> list[MetricGroup]:
        grouped: dict[ResourceSpec, MetricGroup] = {}
        for metric in metric_results:
            key = metric.metadata.identity
            group = grouped.setdefault(key, MetricGroup(key=key))
            group.metrics.append(metric)

        name_counts: dict[str, int] = {}
        for key in grouped:
            name = key.locator.function_name
            name_counts[name] = name_counts.get(name, 0) + 1

        groups = sorted(
            grouped.values(),
            key=lambda g: (
                not g.has_failures,
                _SCOPE_ORDER.get(g.key.scope, 99),
                g.display_name or g.key.locator.function_name,
            ),
        )
        for group in groups:
            origin = group.key.locator.module_path
            path_str = None if origin is None else str(origin)
            provider = (
                safe_relative_path(Path(path_str)).as_posix()
                if path_str
                else None
            )
            name = group.key.locator.function_name
            if name_counts[name] > 1 and provider:
                group.display_name = f"{name} @ {provider}"
            else:
                group.display_name = name
        return groups

    def _build_relationships(
        self,
    ) -> tuple[
        dict[ResourceSpec, set[ResourceSpec]],
        dict[ResourceSpec, set[ResourceSpec]],
    ]:
        parents: dict[ResourceSpec, set[ResourceSpec]] = {}
        children: dict[ResourceSpec, set[ResourceSpec]] = {}

        for group in self._groups:
            for metric in group.metrics:
                for dep in (
                    metric.metadata.direct_providers or metric.dependencies
                ):
                    if dep not in self._group_lookup:
                        continue
                    parents.setdefault(group.key, set()).add(dep)
                    children.setdefault(dep, set()).add(group.key)

        return parents, children

    # ── Verbosity modes ───────────────────────────────────────────────────────

    def _add_minimal(self, renderables: list[RenderableType]) -> None:
        failed_count = sum(1 for g in self._groups if g.has_failures)
        if failed_count:
            renderables.append(
                Text(f"{failed_count} failed metric groups", style="yellow")
            )

    def _add_overview(self, renderables: list[RenderableType]) -> None:
        renderables.append(Text("OVERVIEW", style="bold cyan"))
        renderables.append(self._overview_table())

    def _add_breakdown(self, renderables: list[RenderableType]) -> None:
        detail_groups = [
            g
            for g in self._groups
            if g.is_interesting(self._parents, self._children)
        ]
        if not detail_groups:
            return
        renderables.append(Text(""))
        renderables.append(Text("BREAKDOWN", style="bold cyan"))
        for group in detail_groups:
            renderables.append(Text(""))
            renderables.append(self._detail_panel(group))

    # ── Overview table ────────────────────────────────────────────────────────

    def _overview_table(self) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("Metric")
        table.add_column("Scope", no_wrap=True)
        table.add_column("Value", justify="right")
        table.add_column("Assertions")
        table.add_column("Contributors", no_wrap=True)

        for group in self._groups:
            match len(group.metrics):
                case 1:
                    scope_cell = Text(group.key.scope.value, style="dim")
                case n:
                    scope_text = Text(group.key.scope.value, style="dim")
                    scope_text.append(f" ×{n}")
                    scope_cell = scope_text
            name_style = "bold red" if group.has_failures else "bold"
            table.add_row(
                Text(group.display_name, style=name_style),
                scope_cell,
                Text(group.value_summary(), style="bold"),
                self._assertion_summary(group),
                self._contributor_counts(group),
            )

        return table

    # ── Detail panel ──────────────────────────────────────────────────────────

    def _detail_panel(self, group: MetricGroup) -> Panel:
        renderables: list[RenderableType] = [self._summary_grid(group)]

        hierarchy = self._hierarchy_tree(group)
        if hierarchy is not None:
            self._append_section(
                renderables, "Hierarchy", hierarchy, inline=True
            )

        contributors = self._contributors_grid(group)
        if contributors is not None:
            self._append_section(
                renderables, "Contributors", contributors, inline=True
            )

        self._append_section(
            renderables, "Instances", self._instances_table(group)
        )

        assertions = self._assertions_block(group)
        if assertions is not None:
            self._append_section(renderables, "Assertions", assertions)

        border_style = "red" if group.has_failures else "cyan"
        title_style = "bold red" if group.has_failures else "bold"
        return Panel(
            Group(*renderables),
            title=Text(group.display_name, style=title_style),
            title_align="left",
            border_style=border_style,
            expand=True,
            padding=(1, 1),
        )

    def _summary_grid(self, group: MetricGroup) -> Table:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold", no_wrap=True)
        table.add_column()
        table.add_row("Scope", Text(group.key.scope.value, style="dim"))
        table.add_row("Instances", str(len(group.metrics)))
        table.add_row("Value", Text(group.value_summary(), style="bold"))

        origin = group.key.locator.module_path
        path_str = None if origin is None else str(origin)
        if path_str:
            table.add_row(
                "Path",
                Text(
                    safe_relative_path(Path(path_str)).as_posix(),
                    style="dim",
                ),
            )

        return table

    # ── Hierarchy tree ────────────────────────────────────────────────────────

    def _hierarchy_tree(self, group: MetricGroup) -> Tree | None:
        if group.key not in self._parents and group.key not in self._children:
            return None

        root_key = self._find_root(group.key)
        root_group = self._group_lookup[root_key]
        tree = Tree(self._tree_label(root_group, current=group.key == root_key))
        self._populate_tree(
            tree, root_key, highlight=group.key, seen={root_key}
        )
        return tree

    def _find_root(self, key: ResourceSpec) -> ResourceSpec:
        roots = self._parents.get(key, set())
        if len(roots) != 1:
            return key
        root = next(iter(roots))
        while len(self._parents.get(root, set())) == 1:
            parent = next(iter(self._parents[root]))
            if parent == root:
                break
            root = parent
        return root

    def _populate_tree(
        self,
        tree: Tree,
        key: ResourceSpec,
        *,
        highlight: ResourceSpec,
        seen: set[ResourceSpec],
    ) -> None:
        for child_key in sorted(
            self._children.get(key, set()),
            key=lambda k: self._group_lookup[k].display_name,
        ):
            child_group = self._group_lookup[child_key]
            node = tree.add(
                self._tree_label(child_group, current=child_key == highlight)
            )
            if child_key not in seen:
                self._populate_tree(
                    node,
                    child_key,
                    highlight=highlight,
                    seen={*seen, child_key},
                )

    # ── Contributors ──────────────────────────────────────────────────────────

    def _contributors_grid(self, group: MetricGroup) -> Table | None:
        rows = [
            (
                "Modules",
                self._format_values(group.consumer_modules(), path=True),
            ),
            (
                "Tests",
                self._format_values(group.test_consumers()),
            ),
            (
                "Resources",
                self._format_values(group.resource_consumers()),
            ),
            (
                "Cases",
                self._format_values(group.consumer_cases(), case=True),
            ),
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

    # ── Instances table ───────────────────────────────────────────────────────

    def _instances_table(self, group: MetricGroup) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("Suffix", no_wrap=True)
        table.add_column("Module")
        table.add_column("Tests")
        table.add_column("Value", justify="right")
        table.add_column("Assertions")

        for metric in sorted(group.metrics, key=self._metric_sort_key):
            mv = MetricValue.from_result(metric)
            table.add_row(
                self._instance_label(metric),
                self._format_values(
                    MetricGroup._consumer_modules(
                        metric.metadata.consumers
                    ),
                    path=True,
                )
                or "—",
                self._format_values(
                    MetricGroup._test_consumers(metric.metadata.consumers)
                )
                or "—",
                Text(mv.value_str, style="bold"),
                self._instance_assertions(metric),
            )
        return table

    # ── Assertions block ──────────────────────────────────────────────────────

    def _assertions_block(self, group: MetricGroup) -> Group | None:
        blocks: list[RenderableType] = []
        show_instance = len(group.metrics) > 1

        for metric in sorted(group.metrics, key=self._metric_sort_key):
            instance = self._instance_label(metric)
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

    # ── Cell formatters ───────────────────────────────────────────────────────

    def _assertion_summary(self, group: MetricGroup) -> Text:
        if not group.assertions:
            return Text("")

        seen: set[str] = set()
        snippets: list[Text] = []
        for assertion in group.assertions:
            snippet = self._assertion_snippet(assertion)
            if snippet.plain not in seen:
                seen.add(snippet.plain)
                snippets.append(snippet)

        summary = Text()
        for i, snippet in enumerate(snippets[:2]):
            if i:
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
        expr = self._strip_metric_prefix(expr)

        style = "red" if not assertion.passed else "green"
        resolved: list[tuple[str, str]] = []
        for label, value in assertion.expression_repr.resolved_args.items():
            normalized = self._strip_metric_prefix(oneline(label))
            if normalized:
                resolved.append((normalized, oneline(value)))
        resolved.sort(key=lambda item: len(item[0]), reverse=True)

        snippet = Text()
        i = 0
        while i < len(expr):
            match next(
                ((l, v) for l, v in resolved if expr.startswith(l, i)),
                None,
            ):
                case (label, value):
                    snippet.append(label, style="grey62")
                    snippet.append(" / ", style="dim")
                    snippet.append(value)
                    i += len(label)
                case None:
                    snippet.append(expr[i], style=style)
                    i += 1

        return snippet

    def _contributor_counts(self, group: MetricGroup) -> Text:
        text = Text()
        for i, (label, count) in enumerate(
            [
                ("M", len(group.consumer_modules())),
                ("T", len(group.test_consumers())),
                ("R", len(group.resource_consumers())),
                ("C", len(group.consumer_cases())),
            ]
        ):
            if i:
                text.append(" ")
            text.append(label, style="bold")
            text.append(str(count), style="dim")
        return text

    def _instance_label(self, metric: MetricResult) -> str:
        case_id = metric.primary_case_id
        if case_id:
            return f"[{case_id}]"
        ident = metric.metadata.identity
        origin = ident.locator.module_path
        p = None if origin is None else str(origin)
        label = safe_relative_path(Path(p)).as_posix() if p else None
        return truncate(label or "metric", 28)

    def _instance_assertions(self, metric: MetricResult) -> Text:
        mv = MetricValue.from_result(metric)
        if not mv.total:
            return Text("")
        snippet = self._assertion_summary(
            MetricGroup(metric.metadata.identity, [metric])
        )
        if snippet.plain:
            return snippet
        style = "red" if mv.has_failures else "green"
        return Text(f"{mv.passed}/{mv.total}", style=style)

    def _metric_sort_key(self, metric: MetricResult) -> tuple[str, str]:
        ident = metric.metadata.identity
        origin = ident.locator.module_path
        p = None if origin is None else str(origin)
        provider = safe_relative_path(Path(p)).as_posix() if p else ""
        return (metric.primary_case_id, provider)

    # ── Layout helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _append_section(
        renderables: list[RenderableType],
        title: str,
        body: RenderableType,
        *,
        inline: bool = False,
    ) -> None:
        renderables.append(Text(""))
        if inline:
            table = Table.grid(expand=False, padding=(0, 2))
            table.add_column(no_wrap=True, style="bold cyan")
            table.add_column()
            table.add_row(title, body)
            renderables.append(table)
        else:
            renderables.append(Text(title, style="bold cyan"))
            renderables.append(body)

    @staticmethod
    def _tree_label(group: MetricGroup, *, current: bool) -> Text:
        text = Text(
            group.display_name, style="bold cyan" if current else ""
        )
        if group.key.scope:
            text.append(f" [{group.key.scope.value}]", style="dim")
        return text

    @staticmethod
    def _strip_metric_prefix(expr: str) -> str:
        if "." not in expr:
            return expr
        prefix, rest = expr.split(".", 1)
        if _METRIC_PREFIX_RE.fullmatch(prefix):
            return rest
        return expr

    @staticmethod
    def _format_values(
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
            items = [
                safe_relative_path(Path(v)).as_posix() if v else v
                for v in items
            ]
        if case:
            items = [f"[{v}]" for v in items]
        rendered = ", ".join(items[:limit])
        if len(items) > limit:
            rendered += f" +{len(items) - limit}"
        return rendered
