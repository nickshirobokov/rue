"""Rich rendering for experiment results."""

from __future__ import annotations

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from rue.experiments.models import ExperimentVariantResult


class ExperimentRenderer:
    """Render experiment variant comparisons."""

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
        table.add_row("Run", str(result.run_id))
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
            table.add_column("Node Key")
            table.add_column("Error")

        for label, status, node_key, error in result.failures:
            row = [status, label]
            if verbosity >= 2:
                row.extend([node_key or "", error or ""])
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
