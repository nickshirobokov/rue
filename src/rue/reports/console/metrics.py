"""Renders the METRICS section at the end of a run."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich import box
from rich.console import RenderableType
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from rue.resources import Scope

from .shared import format_label

if TYPE_CHECKING:
    from rue.resources.metrics.base import MetricResult


@dataclass(frozen=True, slots=True)
class MetricValue:
    value_str: str
    passed: int
    total: int
    has_failures: bool


class MetricsRenderer:
    def render(
        self, metric_results: list[MetricResult], verbosity: int
    ) -> list[RenderableType]:
        if not metric_results:
            return []

        renderables: list[RenderableType] = [Rule("METRICS", characters="=")]

        if verbosity < 0:
            failed_count = sum(
                1 for m in metric_results if self._evaluate(m).has_failures
            )
            if failed_count:
                renderables.append(
                    Text(f"{failed_count} failed — see DB for details", style="yellow")
                )
            return renderables

        if verbosity == 0:
            session_metrics = [
                m for m in metric_results if m.metadata.scope == Scope.SESSION
            ]
            if session_metrics:
                renderables.append(self._build_table(session_metrics))
            return renderables

        case_metrics = [m for m in metric_results if m.metadata.scope == Scope.CASE]
        other_metrics = [m for m in metric_results if m.metadata.scope != Scope.CASE]
        if other_metrics:
            renderables.append(self._build_table(other_metrics))
        if case_metrics:
            renderables.extend(self._build_case_section(case_metrics))
        return renderables

    def _evaluate(self, metric: MetricResult) -> MetricValue:
        value = metric.value
        value_str = (
            "N/A" if isinstance(value, float) and math.isnan(value) else str(value)
        )
        assertions = metric.assertion_results
        passed = sum(1 for a in assertions if a.passed)
        total = len(assertions)
        return MetricValue(value_str, passed, total, any(not a.passed for a in assertions))

    def _display_name(self, metric: MetricResult) -> str:
        name = metric.name
        if metric.metadata.scope == Scope.CASE and metric.metadata.collected_from_tests:
            tests = sorted(metric.metadata.collected_from_tests)
            case_suffix = ""
            if metric.metadata.collected_from_cases:
                cases = sorted(metric.metadata.collected_from_cases)
                case_suffix = format_label(cases[0])
            name = f"{name}::{tests[0]}{case_suffix}"
        return name

    def _case_label(self, metric: MetricResult) -> str:
        cases = sorted(metric.metadata.collected_from_cases)
        if cases:
            return cases[0]
        if metric.execution_id:
            return str(metric.execution_id)[:8]
        return "case"

    def _assertions_cell(self, mv: MetricValue) -> Text:
        if not mv.total:
            return Text("")
        color = "red" if mv.has_failures else "green"
        return Text(f"{mv.passed}/{mv.total}", style=color)

    def _build_table(self, metrics: list[MetricResult]) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Assertions", justify="right")
        for m in metrics:
            mv = self._evaluate(m)
            table.add_row(self._display_name(m), mv.value_str, self._assertions_cell(mv))
        return table

    def _build_case_section(
        self, case_metrics: list[MetricResult]
    ) -> list[RenderableType]:
        grouped: dict[str, list[MetricResult]] = {}
        for m in case_metrics:
            grouped.setdefault(m.name, []).append(m)

        renderables: list[RenderableType] = []
        for metric_name in sorted(grouped):
            renderables.append(Text(f" • {metric_name}"))
            table = Table(show_header=False, box=box.SIMPLE, pad_edge=False)
            table.add_column("Case", no_wrap=True)
            table.add_column("Value", justify="right")
            table.add_column("Assertions", justify="right")
            for m in grouped[metric_name]:
                mv = self._evaluate(m)
                table.add_row(
                    format_label(self._case_label(m)),
                    mv.value_str,
                    self._assertions_cell(mv),
                )
            renderables.append(table)
        return renderables
