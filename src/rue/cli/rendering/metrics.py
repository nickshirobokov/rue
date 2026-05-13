"""Metric result rendering."""

# ruff: noqa: D102

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from rue.cli.rendering.assertions import AssertionView
from rue.cli.rendering.primitives import safe_relative_path, truncate
from rue.models import Spec
from rue.resources import ResourceSpec, Scope


if TYPE_CHECKING:
    from rue.resources.metrics.models import MetricResult


_SCOPE_ORDER = {
    Scope.SUITE: 0,
    Scope.MODULE: 1,
    Scope.TEST: 2,
}


@dataclass(frozen=True, slots=True)
class _MetricValueView:
    """Small display projection of one metric value and assertion counts."""

    value_str: str
    passed: int
    total: int
    has_failures: bool

    @classmethod
    def from_result(
        cls, metric: MetricResult
    ) -> _MetricValueView:
        value = metric.value
        value_str = (
            "N/A"
            if isinstance(value, float) and math.isnan(value)
            else str(value)
        )
        assertions = metric.assertion_results
        passed = sum(1 for assertion in assertions if assertion.passed)
        return cls(
            value_str=value_str,
            passed=passed,
            total=len(assertions),
            has_failures=any(not assertion.passed for assertion in assertions),
        )


@dataclass(frozen=True, slots=True)
class MetricGroupView:
    """Render one logical metric grouped across repeated instances."""

    key: ResourceSpec
    metrics: tuple[MetricResult, ...]
    display_name: str = ""

    @classmethod
    def from_results(
        cls,
        identity: ResourceSpec,
        metrics: tuple[MetricResult, ...],
        *,
        display_name: str = "",
    ) -> MetricGroupView:
        """Build a display group for one metric identity."""
        return cls(key=identity, metrics=metrics, display_name=display_name)

    @property
    def assertions(self) -> tuple[AssertionView, ...]:
        return tuple(
            AssertionView.from_result(assertion)
            for metric in self.metrics
            for assertion in metric.assertion_results
        )

    @property
    def has_failures(self) -> bool:
        return any(metric.has_failures for metric in self.metrics)

    @property
    def scope_label(self) -> str:
        return self.key.scope.value

    @property
    def value_summary(self) -> str:
        values = [
            _MetricValueView.from_result(metric).value_str
            for metric in self.metrics
        ]
        numeric_values = [
            value
            for metric in self.metrics
            if isinstance(value := metric.value, (int, float))
            and not isinstance(value, bool)
        ]
        match values:
            case [single]:
                return single
            case _ if len(set(values)) == 1:
                return f"{values[0]} ×{len(values)}"  # noqa: RUF001
            case _ if numeric_values and len(numeric_values) == len(
                self.metrics
            ):
                floats = [float(value) for value in numeric_values]
                return f"{min(floats):g}..{max(floats):g}"
            case _:
                return f"{len(values)} values"

    @property
    def consumers(self) -> tuple[Spec, ...]:
        return tuple(
            consumer
            for metric in self.metrics
            for consumer in metric.metadata.consumers
        )

    @property
    def consumer_modules(self) -> set[Path]:
        return self.consumer_modules_for(self.consumers)

    @property
    def test_consumers(self) -> set[str]:
        return self.test_consumers_for(self.consumers)

    @property
    def resource_consumers(self) -> set[str]:
        return self.resource_consumers_for(self.consumers)

    @property
    def consumer_cases(self) -> set[str]:
        cases = {
            str(case_id)
            for consumer in self.consumers
            if (case_id := getattr(consumer, "case_id", None)) is not None
        }
        cases.update(
            suffix
            for consumer in self.consumers
            if (suffix := getattr(consumer, "suffix", None))
        )
        return cases

    def is_interesting(self, suite_view: MetricSuiteView) -> bool:
        """Return whether this group needs verbose breakdown output."""
        return (
            self.has_failures
            or len(self.metrics) > 1
            or len(self.consumer_modules) > 1
            or len(self.resource_consumers) > 1
            or self.key in suite_view.parents
            or self.key in suite_view.children
        )

    def instance_label(self, metric: MetricResult) -> str:
        case_id = metric.primary_case_id
        if case_id:
            return f"[{case_id}]"
        origin = metric.metadata.identity.locator.module_path
        return truncate(safe_relative_path(origin).as_posix(), 28)

    def metric_sort_key(self, metric: MetricResult) -> tuple[str, str]:
        origin = metric.metadata.identity.locator.module_path
        return (metric.primary_case_id, safe_relative_path(origin).as_posix())

    def add_overview_row(self, table: Table) -> None:
        match len(self.metrics):
            case 1:
                scope_cell = Text(self.scope_label, style="dim")
            case n:
                scope_text = Text(self.scope_label, style="dim")
                scope_text.append(f" ×{n}")  # noqa: RUF001
                scope_cell = scope_text
        name_style = "bold red" if self.has_failures else "bold"
        table.add_row(
            Text(self.display_name, style=name_style),
            scope_cell,
            Text(self.value_summary, style="bold"),
            self.assertion_summary(),
            self.contributor_counts(),
        )

    def detail_panel(self, suite_view: MetricSuiteView) -> Panel:
        """Render the verbose panel for a metric group."""
        renderables: list[RenderableType] = [self.summary_grid()]

        hierarchy = self.hierarchy_tree(suite_view)
        if hierarchy is not None:
            self._append_section(
                renderables, "Hierarchy", hierarchy, inline=True
            )

        contributors = self.contributors_grid()
        if contributors is not None:
            self._append_section(
                renderables, "Contributors", contributors, inline=True
            )

        self._append_section(
            renderables, "Instances", self.instances_table()
        )

        assertions = self.assertions_block()
        if assertions is not None:
            self._append_section(renderables, "Assertions", assertions)

        border_style = "red" if self.has_failures else "cyan"
        title_style = "bold red" if self.has_failures else "bold"
        return Panel(
            Group(*renderables),
            title=Text(self.display_name, style=title_style),
            title_align="left",
            border_style=border_style,
            expand=True,
            padding=(1, 1),
        )

    def summary_grid(self) -> Table:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold", no_wrap=True)
        table.add_column()
        table.add_row("Scope", Text(self.scope_label, style="dim"))
        table.add_row("Instances", str(len(self.metrics)))
        table.add_row("Value", Text(self.value_summary, style="bold"))
        provider_path = safe_relative_path(
            self.key.locator.module_path
        ).as_posix()
        table.add_row("Path", Text(provider_path, style="dim"))

        return table

    def hierarchy_tree(self, suite_view: MetricSuiteView) -> Tree | None:
        """Render provider dependency hierarchy when this metric has one."""
        if (
            self.key not in suite_view.parents
            and self.key not in suite_view.children
        ):
            return None

        root_key = suite_view.find_root(self.key)
        root_group = suite_view.group_lookup[root_key]
        tree = Tree(root_group.tree_label(current=self.key == root_key))
        root_group.populate_tree(
            tree,
            root_key,
            suite_view,
            highlight=self.key,
            seen={root_key},
        )
        return tree

    def populate_tree(
        self,
        tree: Tree,
        key: ResourceSpec,
        suite_view: MetricSuiteView,
        *,
        highlight: ResourceSpec,
        seen: set[ResourceSpec],
    ) -> None:
        _ = self
        for child_key in sorted(
            suite_view.children.get(key, set()),
            key=lambda k: suite_view.group_lookup[k].display_name,
        ):
            child_group = suite_view.group_lookup[child_key]
            node = tree.add(
                child_group.tree_label(current=child_key == highlight)
            )
            if child_key not in seen:
                child_group.populate_tree(
                    node,
                    child_key,
                    suite_view,
                    highlight=highlight,
                    seen={*seen, child_key},
                )

    def contributors_grid(self) -> Table | None:
        rows = [
            (
                "Modules",
                self._format_values(self.consumer_modules),
            ),
            (
                "Tests",
                self._format_values(self.test_consumers),
            ),
            (
                "Resources",
                self._format_values(self.resource_consumers),
            ),
            (
                "Cases",
                self._format_values(self.consumer_cases, case=True),
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

    def instances_table(self) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("Suffix", no_wrap=True)
        table.add_column("Module")
        table.add_column("Tests")
        table.add_column("Value", justify="right")
        table.add_column("Assertions")

        for metric in sorted(self.metrics, key=self.metric_sort_key):
            metric_view = _MetricValueView.from_result(metric)
            table.add_row(
                self.instance_label(metric),
                self._format_values(
                    self.consumer_modules_for(tuple(metric.metadata.consumers)),
                )
                or "—",
                self._format_values(
                    self.test_consumers_for(tuple(metric.metadata.consumers))
                )
                or "—",
                Text(metric_view.value_str, style="bold"),
                self.instance_assertions(metric),
            )
        return table

    def assertions_block(self) -> Group | None:
        """Render metric assertion details grouped by instance."""
        blocks: list[RenderableType] = []
        show_instance = len(self.metrics) > 1

        for metric in sorted(self.metrics, key=self.metric_sort_key):
            instance = self.instance_label(metric)
            for assertion in metric.assertion_results:
                heading = (
                    f"Metric Assertion {instance}"
                    if show_instance
                    else "Metric Assertion"
                )
                if blocks:
                    blocks.append(Text(""))
                blocks.append(
                    AssertionView.from_result(assertion).render(heading)
                )

        return Group(*blocks) if blocks else None

    def assertion_summary(self) -> Text:
        if not self.assertions:
            return Text("")

        seen: set[str] = set()
        snippets: list[Text] = []
        for assertion in self.assertions:
            snippet = assertion.snippet(strip_metric_prefix=True)
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

    def contributor_counts(self) -> Text:
        text = Text()
        for i, (label, count) in enumerate(
            [
                ("M", len(self.consumer_modules)),
                ("T", len(self.test_consumers)),
                ("R", len(self.resource_consumers)),
                ("C", len(self.consumer_cases)),
            ]
        ):
            if i:
                text.append(" ")
            text.append(label, style="bold")
            text.append(str(count), style="dim")
        return text

    def instance_assertions(self, metric: MetricResult) -> Text:
        metric_view = _MetricValueView.from_result(metric)
        if not metric_view.total:
            return Text("")
        snippet = MetricGroupView.from_results(
            metric.metadata.identity,
            (metric,),
            display_name=self.display_name,
        ).assertion_summary()
        if snippet.plain:
            return snippet
        style = "red" if metric_view.has_failures else "green"
        return Text(f"{metric_view.passed}/{metric_view.total}", style=style)

    def tree_label(self, *, current: bool) -> Text:
        text = Text(
            self.display_name, style="bold cyan" if current else ""
        )
        if self.scope_label:
            text.append(f" [{self.scope_label}]", style="dim")
        return text

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
    def _format_values(
        values: set[str | Path],
        *,
        case: bool = False,
        limit: int = 4,
    ) -> str:
        if not values:
            return ""
        items = [
            safe_relative_path(value).as_posix()
            if isinstance(value, Path)
            else value
            for value in sorted(values, key=str)
        ]
        if case:
            items = [f"[{v}]" for v in items]
        rendered = ", ".join(items[:limit])
        if len(items) > limit:
            rendered += f" +{len(items) - limit}"
        return rendered

    @staticmethod
    def consumer_modules_for(consumers: tuple[Spec, ...]) -> set[Path]:
        return {consumer.locator.module_path for consumer in consumers}

    @staticmethod
    def test_consumers_for(consumers: tuple[Spec, ...]) -> set[str]:
        return {
            consumer.locator.function_name
            for consumer in consumers
            if not isinstance(consumer, ResourceSpec)
        }

    @staticmethod
    def resource_consumers_for(consumers: tuple[Spec, ...]) -> set[str]:
        return {
            consumer.locator.function_name
            for consumer in consumers
            if isinstance(consumer, ResourceSpec)
        }


@dataclass(frozen=True, slots=True)
class MetricSuiteView:
    """Render all metric results for one completed suite."""

    groups: tuple[MetricGroupView, ...]
    group_lookup: dict[ResourceSpec, MetricGroupView]
    parents: dict[ResourceSpec, set[ResourceSpec]]
    children: dict[ResourceSpec, set[ResourceSpec]]

    @classmethod
    def from_results(
        cls,
        metric_results: list[MetricResult],
    ) -> MetricSuiteView:
        """Group metric results and derive provider relationships."""
        grouped: dict[ResourceSpec, list[MetricResult]] = {}
        for metric in metric_results:
            grouped.setdefault(metric.metadata.identity, []).append(metric)

        name_counts: dict[str, int] = {}
        for key in grouped:
            name = key.locator.function_name
            name_counts[name] = name_counts.get(name, 0) + 1

        groups = []
        for key, metrics in grouped.items():
            name = key.locator.function_name
            provider = safe_relative_path(key.locator.module_path).as_posix()
            display_name = (
                f"{name} @ {provider}"
                if name_counts[name] > 1
                else name
            )
            groups.append(
                MetricGroupView.from_results(
                    key,
                    tuple(metrics),
                    display_name=display_name,
                )
            )

        ordered = tuple(
            sorted(
                groups,
                key=lambda group: (
                    not group.has_failures,
                    _SCOPE_ORDER.get(group.key.scope, 99),
                    group.display_name or group.key.locator.function_name,
                ),
            )
        )
        group_lookup = {group.key: group for group in ordered}
        parents, children = cls._build_relationships(ordered, group_lookup)
        return cls(
            groups=ordered,
            group_lookup=group_lookup,
            parents=parents,
            children=children,
        )

    @property
    def failed_group_count(self) -> int:
        return sum(1 for group in self.groups if group.has_failures)

    @property
    def detail_groups(self) -> tuple[MetricGroupView, ...]:
        return tuple(
            group for group in self.groups if group.is_interesting(self)
        )

    def render(self, verbosity: int) -> list[RenderableType]:
        """Render metrics using the same verbosity contract as suite output."""
        renderables: list[RenderableType] = [
            Rule(Text("METRICS", style="bold cyan"), characters="=")
        ]
        if not self.groups:
            return renderables

        match verbosity:
            case -1:
                self.add_minimal(renderables)
            case 0:
                self.add_overview(renderables)
            case _:
                self.add_overview(renderables)
                self.add_breakdown(renderables)

        return renderables

    def add_minimal(self, renderables: list[RenderableType]) -> None:
        if self.failed_group_count:
            renderables.append(
                Text(
                    f"{self.failed_group_count} failed metric groups",
                    style="yellow",
                )
            )

    def add_overview(self, renderables: list[RenderableType]) -> None:
        renderables.append(Text("OVERVIEW", style="bold cyan"))
        renderables.append(self.overview_table())

    def add_breakdown(self, renderables: list[RenderableType]) -> None:
        detail_groups = self.detail_groups
        if not detail_groups:
            return
        renderables.append(Text(""))
        renderables.append(Text("BREAKDOWN", style="bold cyan"))
        for group in detail_groups:
            renderables.append(Text(""))
            renderables.append(group.detail_panel(self))

    def overview_table(self) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("Metric")
        table.add_column("Scope", no_wrap=True)
        table.add_column("Value", justify="right")
        table.add_column("Assertions")
        table.add_column("Contributors", no_wrap=True)

        for group in self.groups:
            group.add_overview_row(table)

        return table

    def find_root(self, key: ResourceSpec) -> ResourceSpec:
        """Find the top ancestor used as the hierarchy tree root."""
        roots = self.parents.get(key, set())
        if len(roots) != 1:
            return key
        root = next(iter(roots))
        while len(self.parents.get(root, set())) == 1:
            parent = next(iter(self.parents[root]))
            if parent == root:
                break
            root = parent
        return root

    @staticmethod
    def _build_relationships(
        groups: tuple[MetricGroupView, ...],
        group_lookup: dict[ResourceSpec, MetricGroupView],
    ) -> tuple[
        dict[ResourceSpec, set[ResourceSpec]],
        dict[ResourceSpec, set[ResourceSpec]],
    ]:
        parents: dict[ResourceSpec, set[ResourceSpec]] = {}
        children: dict[ResourceSpec, set[ResourceSpec]] = {}

        for group in groups:
            for metric in group.metrics:
                for dependency in metric.metadata.direct_providers:
                    if dependency not in group_lookup:
                        continue
                    # Only relationships between displayed metric groups matter.
                    parents.setdefault(group.key, set()).add(dependency)
                    children.setdefault(dependency, set()).add(group.key)

        return parents, children



__all__ = ["MetricGroupView", "MetricSuiteView"]
