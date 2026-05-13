"""Experiment result rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from rue.cli.rendering.primitives import STATUS_STYLES
from rue.experiments.models import ExperimentVariantResult
from rue.testing.execution.test.models import TestStatus


@dataclass
class ExperimentSuiteState:
    """Live state for one experiment variant suite."""

    label: str
    suite_execution_id: UUID
    item_keys: set[int] = field(default_factory=set)
    total_tests: int = 0
    ready_tests: int = 0
    started_count: int = 0
    completed_count: int = 0
    status_counts: dict[TestStatus, int] = field(default_factory=dict)
    phase: str = "starting"
    duration_ms: float = 0
    stopped_early: bool = False


class ExperimentLiveRenderer:
    """Render live experiment session progress."""

    _STATUS_ORDER: tuple[TestStatus, ...] = (
        TestStatus.PASSED,
        TestStatus.FAILED,
        TestStatus.ERROR,
        TestStatus.SKIPPED,
        TestStatus.NOT_RUN,
        TestStatus.XFAILED,
        TestStatus.XPASSED,
    )

    def __init__(self, verbosity: int = 0) -> None:
        self.verbosity = verbosity
        self.states: dict[UUID, ExperimentSuiteState] = {}

    def configure(self, verbosity: int) -> None:
        """Apply verbosity for future live renders."""
        self.verbosity = verbosity

    def render(self) -> Panel:
        """Render the live experiment progress panel."""
        table = Table(show_header=True, expand=True)
        table.add_column("Variant")
        table.add_column("Suite", no_wrap=True)
        table.add_column("Progress", justify="right", no_wrap=True)
        table.add_column("Status")
        table.add_column("Phase", no_wrap=True)
        table.add_column("Duration", justify="right", no_wrap=True)

        for state in self.states.values():
            table.add_row(
                state.label,
                str(state.suite_execution_id)[:8],
                self.progress_text(state),
                self.status_text(state),
                state.phase,
                self.duration_text(state),
            )

        return Panel(
            table,
            title="Running experiments...",
            title_align="left",
            border_style="cyan",
            padding=(0, 1),
        )

    def completed_line(self, state: ExperimentSuiteState) -> Text:
        """Render one completed variant line for non-terminal output."""
        text = Text()
        text.append(f"variant {state.label}: ", style="bold")
        text.append_text(self.status_text(state))
        duration = self.duration_text(state)
        if duration:
            text.append(f" in {duration}", style="dim")
        return text

    def progress_text(self, state: ExperimentSuiteState) -> str:
        """Return completed/total progress text for a variant."""
        if not state.total_tests:
            return "0/0"
        return f"{state.completed_count}/{state.total_tests}"

    def status_text(self, state: ExperimentSuiteState) -> Text:
        """Render status counts for a variant."""
        text = Text()
        for status in self._STATUS_ORDER:
            count = state.status_counts.get(status, 0)
            if not count:
                continue
            if text.plain:
                text.append("  ")
            style = STATUS_STYLES[status]
            text.append(f"{style.symbol} {count}", style=style.color)
        if not text.plain:
            text.append("pending", style="dim")
        return text

    def duration_text(self, state: ExperimentSuiteState) -> str:
        """Return formatted duration text when a variant has finished."""
        if state.duration_ms <= 0:
            return ""
        return f"{state.duration_ms / 1000:.2f}s"


class ExperimentRenderer:
    """Render final experiment variant rankings and verbose details."""

    def render(
        self,
        results: tuple[ExperimentVariantResult, ...],
        verbosity: int,
    ) -> list[RenderableType]:
        """Render experiment results for the selected verbosity."""
        if not results:
            return [Text("No experiments found.", style="yellow")]

        ranked = tuple(
            sorted(results, key=lambda result: result.rank_key, reverse=True)
        )
        # The final report is deterministic regardless of execution order.
        renderables: list[RenderableType] = [
            Rule(Text("EXPERIMENTS", style="bold cyan"), characters="="),
            self._overview(ranked),
        ]
        if verbosity >= 1:
            renderables.extend(self._details(ranked, verbosity))
        return renderables

    def _overview(
        self,
        results: tuple[ExperimentVariantResult, ...],
    ) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("Variant")
        table.add_column("Pass Rate", justify="right", no_wrap=True)
        table.add_column("Passed", justify="right", no_wrap=True)
        table.add_column("Failed", justify="right", no_wrap=True)
        table.add_column("Errors", justify="right", no_wrap=True)
        table.add_column("Metrics")
        table.add_column("Duration", justify="right", no_wrap=True)

        for rank, result in enumerate(results, start=1):
            style = "bold green" if rank == 1 else ""
            table.add_row(
                str(rank),
                Text(result.variant.label, style=style),
                f"{result.pass_rate:.0%}",
                str(result.passed),
                str(result.failed),
                str(result.errors),
                self._metric_summary(result),
                f"{result.total_duration_ms / 1000:.2f}s",
            )
        return table

    def _details(
        self,
        results: tuple[ExperimentVariantResult, ...],
        verbosity: int,
    ) -> list[RenderableType]:
        renderables: list[RenderableType] = []
        for result in results:
            rows: list[RenderableType] = [self._variant_grid(result)]
            if result.failures:
                rows.append(Text(""))
                rows.append(self._failures_table(result, verbosity))
            if result.metric_values:
                rows.append(Text(""))
                rows.append(self._metrics_table(result))
            border_style = (
                "red" if result.failed or result.errors else "green"
            )
            renderables.append(Text(""))
            renderables.append(
                Panel(
                    Group(*rows),
                    title=Text(result.variant.label, style="bold"),
                    title_align="left",
                    border_style=border_style,
                    expand=True,
                )
            )
        return renderables

    def _variant_grid(self, result: ExperimentVariantResult) -> Table:
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold", no_wrap=True)
        table.add_column()
        table.add_row("Pass Rate", f"{result.pass_rate:.0%}")
        table.add_row(
            "Counts",
            (
                f"{result.passed} passed, {result.failed} failed, "
                f"{result.errors} errors, {result.skipped} skipped"
            ),
        )
        table.add_row("Duration", f"{result.total_duration_ms / 1000:.2f}s")
        table.add_row("suite_execution_id", str(result.suite_execution_id))
        return table

    def _failures_table(
        self,
        result: ExperimentVariantResult,
        verbosity: int,
    ) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("Status", no_wrap=True)
        table.add_column("Test")
        if verbosity >= 2:
            table.add_column("Test execution ID")
            table.add_column("Error")

        for label, status, test_execution_id, error in result.failures:
            row = [status, label]
            if verbosity >= 2:
                row.extend([test_execution_id or "", error or ""])
            table.add_row(*row)
        return table

    @staticmethod
    def _metrics_table(result: ExperimentVariantResult) -> Table:
        table = Table(show_header=True, box=box.SIMPLE, pad_edge=False)
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        for name, value in result.metric_values:
            table.add_row(name, value)
        return table

    @staticmethod
    def _metric_summary(result: ExperimentVariantResult) -> str:
        if not result.metric_values:
            return ""
        values = [
            f"{name}={value}" for name, value in result.metric_values[:4]
        ]
        if len(result.metric_values) > len(values):
            values.append(f"+{len(result.metric_values) - len(values)}")
        return ", ".join(values)


experiment_renderer = ExperimentRenderer()
