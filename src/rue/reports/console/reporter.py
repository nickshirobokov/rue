"""ConsoleReporter: slim orchestrator delegating to focused sub-components."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.rule import Rule
from rich.text import Text

from rue.reports.base import Reporter

from .failures import FailureRenderer
from .live import LiveDisplay
from .metrics import MetricsRenderer
from .modes import OutputMode, make_mode
from .state import SessionState

if TYPE_CHECKING:
    from rue.config import RueConfig
    from rue.testing import TestDefinition
    from rue.testing.execution.interfaces import Test
    from rue.testing.models.result import TestExecution
    from rue.testing.models.run import Run, RunEnvironment


class ConsoleReporter(Reporter):
    def __init__(self, console: Console | None = None, verbosity: int = 0) -> None:
        self.console = console or Console(file=sys.__stdout__)
        self.verbosity = verbosity
        self._state = SessionState()
        self._mode: OutputMode = make_mode(verbosity, self.console)
        self._live = LiveDisplay(self.console)
        self._failures = FailureRenderer()
        self._metrics = MetricsRenderer()

    def configure(self, config: RueConfig) -> None:
        self.verbosity = config.verbosity
        self._mode = make_mode(self.verbosity, self.console)
        self._failures = FailureRenderer(show_locals=config.verbosity >= 2)

    # ── Run header & summary ──────────────────────────────────────────────────

    def _build_run_header(self, environment: RunEnvironment, run_id: object) -> Group:
        parts: list[RenderableType] = [
            Rule("RUE RUN STARTS", characters="="),
            Text(
                f"platform {environment.platform} -- python {environment.python_version}"
                f" -- rue {environment.rue_version}"
            ),
            Text(f"rootdir: {environment.working_directory}"),
        ]
        if run_id:
            parts.append(Text(f"run_id: {run_id}"))
        if environment.branch and environment.commit_hash:
            commit = environment.commit_hash[:8]
            dirty = " dirty" if environment.dirty else ""
            parts.append(Text(f"git: {environment.branch} ({commit}){dirty}"))
        return Group(*parts)

    def _build_summary(self, run: Run) -> Group:
        result = run.result
        parts: list[str] = []
        if result.passed:
            parts.append(f"[green]{result.passed} passed[/green]")
        if result.failed:
            parts.append(f"[red]{result.failed} failed[/red]")
        if result.errors:
            parts.append(f"[yellow]{result.errors} errors[/yellow]")
        if result.skipped:
            parts.append(f"[yellow]{result.skipped} skipped[/yellow]")
        if result.xfailed:
            parts.append(f"[blue]{result.xfailed} xfailed[/blue]")
        if result.xpassed:
            parts.append(f"[magenta]{result.xpassed} xpassed[/magenta]")

        summary = ", ".join(parts) if parts else "[dim]0 tests[/dim]"
        summary_line = f"run_id: {run.run_id}\n{summary} in {result.total_duration_ms:.0f}ms"
        return Group(
            Rule("SUMMARY", characters="="),
            Text.from_markup(f"[bold]{summary_line}[/bold]", justify="center"),
            Rule(characters="="),
        )

    # ── Reporter hooks ────────────────────────────────────────────────────────

    async def on_no_tests_found(self) -> None:
        self.console.print("[yellow]No tests found.[/yellow]")

    async def on_collection_complete(
        self, items: list[TestDefinition], run: Run
    ) -> None:
        self._live.stop()
        self._state.reset(items)

        self.console.print(self._build_run_header(run.environment, run.run_id))
        self.console.print()
        if self._mode.show_collected_count:
            self.console.print(f"[bold]Collected {len(items)} tests[/bold]\n")

        if self.console.is_terminal:
            self._live.start(self._mode.render_live(self._state))

    async def on_tests_ready(self, tests: list[Test]) -> None:
        for test in tests:
            self._state.tests[id(test.definition)] = test

    async def on_test_start(self, item: TestDefinition) -> None:
        if self._live.active:
            self._live.refresh(self._mode.render_live(self._state))

    async def on_execution_complete(self, execution: TestExecution) -> None:
        self._state.executions[id(execution.definition)] = execution

        is_top_level = id(execution.definition) in self._state.item_ids
        if is_top_level:
            self._state.completed_count += 1
            if execution.result.status.is_failure:
                self._state.failures.append(execution)

        if self._live.active:
            self._live.refresh(self._mode.render_live(self._state))
            return

        if not is_top_level:
            return

        self._mode.print_test(execution, self._state)

    async def on_run_complete(self, run: Run) -> None:
        self._live.stop()

        if self.verbosity == 0 and self._state.current_module is not None:
            self.console.print()

        if self._mode.show_failures and self._state.failures:
            for renderable in self._failures.render(self._state.failures):
                self.console.print(renderable)

        if run.result.stopped_early:
            self.console.print("[yellow]Run terminated early.[/yellow]")

        for renderable in self._metrics.render(
            run.result.metric_results, self.verbosity
        ):
            self.console.print(renderable)

        self.console.print()
        self.console.print(self._build_summary(run))

    async def on_run_stopped_early(self, failure_count: int) -> None:
        self.console.print(
            f"\n\n[red]Stopping early after {failure_count} failure(s).[/red]"
        )
