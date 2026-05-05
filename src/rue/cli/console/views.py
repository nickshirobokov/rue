"""Console-specific view models."""

# ruff: noqa: D101,D102

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich import box
from rich.console import Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.traceback import Traceback
from rich.tree import Tree

from rue.models import Spec
from rue.resources import ResourceSpec, Scope

from .shared import (
    STATUS_STYLES,
    StatusStyle,
    dedented_source_block,
    oneline,
    safe_relative_path,
    truncate,
)


if TYPE_CHECKING:
    from rue.assertions import AssertionRepr, AssertionResult
    from rue.resources.metrics.models import MetricResult
    from rue.testing.models import TestStatus
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import ExecutedRun


_COMPACT_MODULE_STYLE = "white"
_MODIFIER_STYLE = "cyan"
_METRIC_PREFIX_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_RUE_MODULE = __import__("rue")
_SCOPE_ORDER = {
    Scope.RUN: 0,
    Scope.MODULE: 1,
    Scope.TEST: 2,
}
_TREE_MODULE_STYLE = "medium_purple"


@dataclass(frozen=True, slots=True)
class ConsoleAssertionView:
    expression_repr: AssertionRepr
    passed: bool
    error_message: str | None

    @classmethod
    def from_result(
        cls,
        assertion: AssertionResult,
    ) -> ConsoleAssertionView:
        return cls(
            expression_repr=assertion.expression_repr,
            passed=assertion.passed,
            error_message=assertion.error_message,
        )

    def render(self, heading: str) -> Text:
        expr = self.expression_repr
        text = Text()
        color = "green" if self.passed else "red"

        text.append("✓ " if self.passed else "✗ ", style=f"bold {color}")
        text.append(heading, style="bold")
        if self.error_message:
            text.append("  ")
            text.append(self.error_message, style="italic")

        above, expr_lines, below = dedented_source_block(expr)

        for line in above:
            text.append("\n")
            text.append(f"│  {line}", style="dim")
        for line in expr_lines:
            text.append("\n")
            text.append(">  ", style=f"bold {color}")
            text.append(line, style="bold")
        for line in below:
            text.append("\n")
            text.append(f"│  {line}", style="dim")

        if expr.resolved_args:
            text.append("\n")
            text.append("│", style="dim")
            text.append("\n")
            text.append("╰─ where:", style="dim italic")
            for name, value in expr.resolved_args.items():
                text.append("\n     ")
                text.append(oneline(name), style="bold")
                text.append(" = ", style="dim")
                text.append(truncate(oneline(value)), style="cyan")

        return text

    def snippet(self, *, strip_metric_prefix: bool = False) -> Text:
        expr = oneline(self.expression_repr.expr)
        if expr.startswith("assert "):
            expr = expr[7:]
        if strip_metric_prefix:
            expr = self._strip_metric_prefix(expr)

        style = "red" if not self.passed else "green"
        resolved: list[tuple[str, str]] = []
        for label, value in self.expression_repr.resolved_args.items():
            normalized = oneline(label)
            if strip_metric_prefix:
                normalized = self._strip_metric_prefix(normalized)
            if normalized:
                resolved.append((normalized, oneline(value)))
        resolved.sort(key=lambda item: len(item[0]), reverse=True)

        snippet = Text()
        i = 0
        while i < len(expr):
            match next(
                (
                    (label, value)
                    for label, value in resolved
                    if expr.startswith(label, i)
                ),
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

    @staticmethod
    def _strip_metric_prefix(expr: str) -> str:
        if "." not in expr:
            return expr
        prefix, rest = expr.split(".", 1)
        if _METRIC_PREFIX_RE.fullmatch(prefix):
            return rest
        return expr


@dataclass(frozen=True, slots=True)
class ConsoleModuleView:
    path: Path | None

    def compact_text(self) -> Text:
        return Text(f" • {self.label} ", style=_COMPACT_MODULE_STYLE)

    def tree_text(self) -> Text:
        return Text(f"• {self.label} ", style=_TREE_MODULE_STYLE)

    @property
    def label(self) -> str:
        if self.path is None:
            return "<unknown>"
        return safe_relative_path(self.path).as_posix()


@dataclass(frozen=True, slots=True)
class ConsoleCapturedOutputView:
    lines: tuple[str, ...]

    @classmethod
    def from_lines(cls, lines: list[str]) -> ConsoleCapturedOutputView:
        return cls(lines=tuple(lines))

    def render(self) -> list[RenderableType]:
        if not self.lines:
            return []
        renderables: list[RenderableType] = [
            Text(""),
            Rule(
                Text("WARNINGS", style="bold yellow"),
                characters="=",
                style="yellow",
            ),
        ]
        for line, count in Counter(self.lines).items():
            label = f"{line} (x{count})" if count > 1 else line
            renderables.append(Text(label, style="yellow dim"))
        renderables.append(Text(""))
        return renderables


@dataclass(frozen=True, slots=True)
class ConsoleRunView:
    run_id: str
    platform: str
    python_version: str
    rue_version: str
    working_directory: str
    branch: str | None
    commit_hash: str | None
    dirty: bool | None
    passed: int
    failed: int
    errors: int
    skipped: int
    xfailed: int
    xpassed: int
    total_duration_ms: float

    @classmethod
    def from_run(cls, run: ExecutedRun) -> ConsoleRunView:
        environment = run.environment
        return cls(
            run_id=str(run.run_id),
            platform=environment.platform,
            python_version=environment.python_version,
            rue_version=environment.rue_version,
            working_directory=environment.working_directory,
            branch=environment.branch,
            commit_hash=environment.commit_hash,
            dirty=environment.dirty,
            passed=run.result.passed,
            failed=run.result.failed,
            errors=run.result.errors,
            skipped=run.result.skipped,
            xfailed=run.result.xfailed,
            xpassed=run.result.xpassed,
            total_duration_ms=run.result.total_duration_ms,
        )

    @property
    def short_commit(self) -> str | None:
        if self.commit_hash is None:
            return None
        return self.commit_hash[:8]

    @property
    def git_summary(self) -> str | None:
        if self.branch is None or self.short_commit is None:
            return None
        dirty = " dirty" if self.dirty else ""
        return f"{self.branch} ({self.short_commit}){dirty}"

    @property
    def summary_markup(self) -> str:
        parts = []
        if self.passed:
            parts.append(f"[bold green]{self.passed} passed[/bold green]")
        if self.failed:
            parts.append(f"[bold red]{self.failed} failed[/bold red]")
        if self.errors:
            parts.append(f"[bold yellow]{self.errors} errors[/bold yellow]")
        if self.skipped:
            parts.append(f"[yellow]{self.skipped} skipped[/yellow]")
        if self.xfailed:
            parts.append(f"[blue]{self.xfailed} xfailed[/blue]")
        if self.xpassed:
            parts.append(f"[magenta]{self.xpassed} xpassed[/magenta]")
        return ", ".join(parts) if parts else "[dim]0 tests[/dim]"

    @property
    def duration_markup(self) -> str:
        return (
            f"{self.summary_markup} "
            f"[dim]in {self.total_duration_ms:.0f}ms[/dim]"
        )

    @property
    def run_id_markup(self) -> str:
        return f"[dim]run_id: {self.run_id}[/dim]"

    def render_header(self) -> Group:
        platform_text = Text()
        platform_text.append("platform ", style="dim")
        platform_text.append(self.platform)
        platform_text.append("  python ", style="dim")
        platform_text.append(self.python_version)
        platform_text.append("  rue ", style="dim")
        platform_text.append(self.rue_version)

        rootdir_text = Text()
        rootdir_text.append("rootdir: ", style="dim")
        rootdir_text.append(self.working_directory)

        parts: list[RenderableType] = [
            Rule(Text("RUE RUN STARTS", style="bold cyan"), characters="="),
            platform_text,
            rootdir_text,
        ]
        if self.run_id:
            run_id_text = Text()
            run_id_text.append("run_id: ", style="dim")
            run_id_text.append(self.run_id, style="dim")
            parts.append(run_id_text)
        if self.git_summary is not None:
            git_text = Text()
            git_text.append("git: ", style="dim")
            git_text.append(self.git_summary)
            parts.append(git_text)
        return Group(*parts)

    def render_summary(self) -> Group:
        return Group(
            Rule(Text("SUMMARY", style="bold cyan"), characters="="),
            Text.from_markup(self.duration_markup, justify="center"),
            Text.from_markup(self.run_id_markup, justify="center"),
            Rule(characters="="),
        )


@dataclass(frozen=True, slots=True)
class ConsoleExecutionView:
    label: str
    local_name: str
    title: str
    status: TestStatus
    status_style: StatusStyle
    duration_ms: float
    status_repr: str
    modifier_suffix: str
    error: BaseException | None
    failed_assertions: tuple[ConsoleAssertionView, ...]
    subviews: tuple[ConsoleExecutionView, ...]

    @classmethod
    def from_execution(
        cls,
        execution: ExecutedTest,
        *,
        verbosity: int = 0,
        title: str | None = None,
    ) -> ConsoleExecutionView:
        spec = execution.definition.spec
        label = spec.get_label(full=verbosity >= 2) or "case"
        summary = ""
        if spec.modifiers and execution.sub_executions:
            summary = spec.modifiers[0].display_summary
        status = execution.result.status
        fallback_title = spec.get_label(full=verbosity >= 2)
        return cls(
            label=label,
            local_name=spec.local_name,
            title=title or fallback_title or execution.label,
            status=status,
            status_style=STATUS_STYLES[status],
            duration_ms=execution.result.duration_ms,
            status_repr=execution.result.status_repr,
            modifier_suffix=f" {summary}" if summary else "",
            error=execution.result.error,
            failed_assertions=tuple(
                ConsoleAssertionView.from_result(assertion)
                for assertion in execution.result.assertion_results
                if not assertion.passed
            ),
            subviews=tuple(
                cls.from_execution(sub, verbosity=verbosity)
                for sub in execution.sub_executions
            ),
        )

    @classmethod
    def render_assertion_failures(
        cls,
        failures: list[ExecutedTest],
        verbosity: int,
    ) -> list[RenderableType]:
        relevant = [
            view
            for view in (
                cls.from_execution(
                    failure,
                    title=failure.definition.spec.full_name,
                    verbosity=verbosity,
                )
                for failure in failures
            )
            if view.has_failed_assertions
        ]
        if not relevant:
            return []
        renderables: list[RenderableType] = [
            Text(""),
            Rule(
                Text("ASSERTIONS", style="bold red"),
                characters="=",
                style="red",
            ),
        ]
        for index, failure in enumerate(relevant):
            if index:
                renderables.append(Text(""))
            renderables.append(failure.assertion_panel())
        renderables.append(Text(""))
        return renderables

    @classmethod
    def render_exception_failures(
        cls,
        failures: list[ExecutedTest],
        verbosity: int,
        *,
        show_locals: bool = False,
    ) -> list[RenderableType]:
        relevant = [
            view
            for view in (
                cls.from_execution(
                    failure,
                    title=failure.definition.spec.full_name,
                    verbosity=verbosity,
                )
                for failure in failures
            )
            if view.has_exception
        ]
        if not relevant:
            return []
        renderables: list[RenderableType] = [
            Text(""),
            Rule(
                Text("ERRORS", style="bold red"),
                characters="=",
                style="red",
            ),
        ]
        for index, failure in enumerate(relevant):
            if index:
                renderables.append(Text(""))
            renderables.append(failure.exception_panel(show_locals=show_locals))
        renderables.append(Text(""))
        return renderables

    @property
    def should_show_error(self) -> bool:
        if self.error is None:
            return False
        return not (
            isinstance(self.error, AssertionError)
            and bool(self.failed_assertions)
        )

    @property
    def has_exception(self) -> bool:
        return self.should_show_error or any(
            subview.has_exception for subview in self.subviews
        )

    @property
    def has_failed_assertions(self) -> bool:
        return bool(self.failed_assertions) or any(
            subview.has_failed_assertions for subview in self.subviews
        )

    @property
    def assertion_subviews(self) -> tuple[ConsoleExecutionView, ...]:
        return tuple(
            subview
            for subview in self.subviews
            if subview.has_failed_assertions
        )

    @property
    def exception_subviews(self) -> tuple[ConsoleExecutionView, ...]:
        return tuple(
            subview for subview in self.subviews if subview.has_exception
        )

    def assertion_panel(self) -> Panel:
        renderables: list[RenderableType] = []

        if self.failed_assertions:
            combined = Text()
            for i, assertion in enumerate(self.failed_assertions):
                if i:
                    combined.append("\n\n")
                combined.append_text(assertion.render("Failed Assertion"))
            renderables.append(combined)

        renderables.extend(
            subview.assertion_panel()
            for subview in self.assertion_subviews
        )
        return self._panel(renderables)

    def exception_panel(self, *, show_locals: bool = False) -> Panel:
        renderables: list[RenderableType] = []

        if self.should_show_error:
            err = self.error
            assert err is not None
            if err.__traceback__:
                renderables.append(
                    Traceback.from_exception(
                        type(err),
                        err,
                        err.__traceback__,
                        suppress=[_RUE_MODULE],
                        show_locals=show_locals,
                    )
                )
            else:
                renderables.append(escape(f"{type(err).__name__}: {err}"))

        renderables.extend(
            subview.exception_panel(show_locals=show_locals)
            for subview in self.exception_subviews
        )
        return self._panel(renderables)

    def render_test_line(
        self,
        *,
        name: str | None = None,
        extra: str = "",
        indent: int = 2,
        sub: bool = False,
    ) -> Text:
        label = name or (self.label if sub else self.local_name)
        text = Text(" " * indent + "• ")
        text.append_text(
            self.sub_label_text(label) if sub else self.test_name_text(label)
        )
        if self.modifier_suffix:
            text.append(self.modifier_suffix, style=_MODIFIER_STYLE)
        text.append(f" ({self.duration_ms:.1f}ms)", style="dim")
        if extra:
            text.append(f" {extra}", style="dim")
        text.append(
            f" {self.status_style.label}", style=self.status_style.color
        )
        return text

    def render_live_item_line(self, *, name: str | None = None) -> Text:
        text = self.test_name_text(name or self.local_name)
        if self.modifier_suffix:
            text.append(self.modifier_suffix, style=_MODIFIER_STYLE)
        text.append(f" ({self.duration_ms:.1f}ms)", style="dim")
        if self.status_repr:
            text.append(f" {self.status_repr}", style="dim")
        text.append(
            f" {self.status_style.label}", style=self.status_style.color
        )
        return text

    def render_sub_live_line(self) -> Text:
        text = self.sub_label_text(self.label)
        if self.modifier_suffix:
            text.append(self.modifier_suffix, style=_MODIFIER_STYLE)
        text.append(f" ({self.duration_ms:.1f}ms)", style="dim")
        text.append(
            f" {self.status_style.label}", style=self.status_style.color
        )
        return text

    def _panel(self, renderables: list[RenderableType]) -> Panel:
        panel_content: RenderableType
        match renderables:
            case []:
                panel_content = " "
            case [single]:
                panel_content = single
            case _:
                panel_content = Group(*renderables)

        return Panel(
            panel_content,
            title=Text(
                self.title,
                style=f"bold {self.status_style.color}",
            ),
            title_align="left",
            border_style=self.status_style.color,
            expand=True,
            padding=(1, 1),
        )

    @staticmethod
    def running_line(name: str) -> Text:
        text = ConsoleExecutionView.test_name_text(name)
        text.append("  ")
        text.append("⋯ running", style="dim")
        return text

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
    def sub_label_text(label: str) -> Text:
        if label.startswith("[") and label.endswith("]"):
            return Text(label)
        text = Text()
        text.append("[", style="dim")
        text.append(label)
        text.append("]", style="dim")
        return text


@dataclass(frozen=True, slots=True)
class _ConsoleMetricValueView:
    value_str: str
    passed: int
    total: int
    has_failures: bool

    @classmethod
    def from_result(
        cls, metric: MetricResult
    ) -> _ConsoleMetricValueView:
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
class ConsoleMetricGroupView:
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
    ) -> ConsoleMetricGroupView:
        return cls(key=identity, metrics=metrics, display_name=display_name)

    @property
    def assertions(self) -> tuple[ConsoleAssertionView, ...]:
        return tuple(
            ConsoleAssertionView.from_result(assertion)
            for metric in self.metrics
            for assertion in metric.assertion_results
        )

    @property
    def has_failures(self) -> bool:
        return any(metric.has_failures for metric in self.metrics)

    @property
    def provider_path(self) -> str | None:
        origin = self.key.locator.module_path
        if origin is None:
            return None
        return safe_relative_path(origin).as_posix()

    @property
    def scope_label(self) -> str:
        return self.key.scope.value

    @property
    def value_summary(self) -> str:
        values = [
            _ConsoleMetricValueView.from_result(metric).value_str
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
    def consumer_modules(self) -> set[str]:
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

    def is_interesting(self, run_view: ConsoleMetricRunView) -> bool:
        return (
            self.has_failures
            or len(self.metrics) > 1
            or len(self.consumer_modules) > 1
            or len(self.resource_consumers) > 1
            or self.key in run_view.parents
            or self.key in run_view.children
        )

    def instance_label(self, metric: MetricResult) -> str:
        case_id = metric.primary_case_id
        if case_id:
            return f"[{case_id}]"
        origin = metric.metadata.identity.locator.module_path
        label = safe_relative_path(origin).as_posix() if origin else None
        return truncate(label or "metric", 28)

    def metric_sort_key(self, metric: MetricResult) -> tuple[str, str]:
        origin = metric.metadata.identity.locator.module_path
        provider = safe_relative_path(origin).as_posix() if origin else ""
        return (metric.primary_case_id, provider)

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

    def detail_panel(self, run_view: ConsoleMetricRunView) -> Panel:
        renderables: list[RenderableType] = [self.summary_grid()]

        hierarchy = self.hierarchy_tree(run_view)
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

        if self.provider_path:
            table.add_row("Path", Text(self.provider_path, style="dim"))

        return table

    def hierarchy_tree(self, run_view: ConsoleMetricRunView) -> Tree | None:
        if (
            self.key not in run_view.parents
            and self.key not in run_view.children
        ):
            return None

        root_key = run_view.find_root(self.key)
        root_group = run_view.group_lookup[root_key]
        tree = Tree(root_group.tree_label(current=self.key == root_key))
        root_group.populate_tree(
            tree,
            root_key,
            run_view,
            highlight=self.key,
            seen={root_key},
        )
        return tree

    def populate_tree(
        self,
        tree: Tree,
        key: ResourceSpec,
        run_view: ConsoleMetricRunView,
        *,
        highlight: ResourceSpec,
        seen: set[ResourceSpec],
    ) -> None:
        _ = self
        for child_key in sorted(
            run_view.children.get(key, set()),
            key=lambda k: run_view.group_lookup[k].display_name,
        ):
            child_group = run_view.group_lookup[child_key]
            node = tree.add(
                child_group.tree_label(current=child_key == highlight)
            )
            if child_key not in seen:
                child_group.populate_tree(
                    node,
                    child_key,
                    run_view,
                    highlight=highlight,
                    seen={*seen, child_key},
                )

    def contributors_grid(self) -> Table | None:
        rows = [
            (
                "Modules",
                self._format_values(self.consumer_modules, path=True),
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
            metric_view = _ConsoleMetricValueView.from_result(metric)
            table.add_row(
                self.instance_label(metric),
                self._format_values(
                    self.consumer_modules_for(tuple(metric.metadata.consumers)),
                    path=True,
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
                    ConsoleAssertionView.from_result(assertion).render(heading)
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
        metric_view = _ConsoleMetricValueView.from_result(metric)
        if not metric_view.total:
            return Text("")
        snippet = ConsoleMetricGroupView.from_results(
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

    @staticmethod
    def consumer_modules_for(consumers: tuple[Spec, ...]) -> set[str]:
        return {
            str(consumer.locator.module_path)
            for consumer in consumers
            if consumer.locator.module_path is not None
        }

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
class ConsoleMetricRunView:
    groups: tuple[ConsoleMetricGroupView, ...]
    group_lookup: dict[ResourceSpec, ConsoleMetricGroupView]
    parents: dict[ResourceSpec, set[ResourceSpec]]
    children: dict[ResourceSpec, set[ResourceSpec]]

    @classmethod
    def from_results(
        cls,
        metric_results: list[MetricResult],
    ) -> ConsoleMetricRunView:
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
            provider = None
            if key.locator.module_path is not None:
                provider = safe_relative_path(
                    Path(str(key.locator.module_path))
                ).as_posix()
            display_name = (
                f"{name} @ {provider}"
                if name_counts[name] > 1 and provider
                else name
            )
            groups.append(
                ConsoleMetricGroupView.from_results(
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
    def detail_groups(self) -> tuple[ConsoleMetricGroupView, ...]:
        return tuple(
            group for group in self.groups if group.is_interesting(self)
        )

    def render(self, verbosity: int) -> list[RenderableType]:
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
        groups: tuple[ConsoleMetricGroupView, ...],
        group_lookup: dict[ResourceSpec, ConsoleMetricGroupView],
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
                    parents.setdefault(group.key, set()).add(dependency)
                    children.setdefault(dependency, set()).add(group.key)

        return parents, children


__all__ = [
    "ConsoleAssertionView",
    "ConsoleCapturedOutputView",
    "ConsoleExecutionView",
    "ConsoleMetricGroupView",
    "ConsoleMetricRunView",
    "ConsoleModuleView",
    "ConsoleRunView",
]
