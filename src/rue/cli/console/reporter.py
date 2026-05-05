"""ConsoleReporter: Rich console processor for Rue test runs."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from rue.events import RunEventsProcessor
from rue.testing.models import TestStatus

from .captured import StderrCapture
from .modes import OutputMode, make_mode
from .shared import STATUS_STYLES
from .views import (
    ConsoleCapturedOutputView,
    ConsoleExecutionView,
    ConsoleMetricRunView,
    ConsoleRunView,
)


if TYPE_CHECKING:
    from rue.config import Config
    from rue.testing import LoadedTestDef
    from rue.testing.execution.executable import ExecutableTest
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import ExecutedRun


class ConsoleReporter(RunEventsProcessor):
    """Rich console processor for Rue test runs."""

    _PROGRESS_STAT_ORDER: tuple[tuple[TestStatus, str], ...] = (
        (TestStatus.PASSED, "passed"),
        (TestStatus.FAILED, "failed"),
        (TestStatus.ERROR, "errors"),
        (TestStatus.SKIPPED, "skipped"),
        (TestStatus.XFAILED, "xfailed"),
        (TestStatus.XPASSED, "xpassed"),
    )

    def __init__(
        self, console: Console | None = None, verbosity: int = 0
    ) -> None:
        self.console = console or Console(file=sys.__stdout__)
        self.verbosity = verbosity
        self._mode: OutputMode = make_mode(verbosity, self.console)
        self._live: Live | None = None
        self._stderr_capture = StderrCapture()
        self._lock = asyncio.Lock()
        self.items: list[LoadedTestDef] = []
        self.item_keys: set[int] = set()
        self.items_by_file: dict[Path | None, list[LoadedTestDef]] = {}
        self.total_tests: int = 0
        self.completed_count: int = 0
        self.tests: dict[int, ExecutableTest] = {}
        self.executions: dict[int, ExecutedTest] = {}
        self.all_executions: dict[int, ExecutedTest] = {}
        self.failures: list[ExecutedTest] = []
        self._status_counts: dict[TestStatus, int] = {}
        self.current_module: Path | None = None
        self.completed_modules: set[Path | None] = set()

    def configure(self, config: Config) -> None:
        """Apply runtime console settings."""
        self.verbosity = config.verbosity
        self._mode = make_mode(self.verbosity, self.console)

    # ── Run header & summary ──────────────────────────────────────────────────

    def _build_run_header(self, run: ExecutedRun) -> RenderableType:
        return ConsoleRunView.from_run(run).render_header()

    def _build_summary(self, run: ExecutedRun) -> RenderableType:
        return ConsoleRunView.from_run(run).render_summary()

    def _build_live_display(self) -> RenderableType:
        if self.items_by_file and len(self.completed_modules) == len(
            self.items_by_file
        ):
            return Text("")
        live = self._mode.render_live(self)
        if not self._mode.show_progress_bar:
            return live
        completed, total = self.completed_count, self.total_tests
        pct = completed / total * 100 if total else 0
        finished = completed == total and total > 0
        bar = ProgressBar(
            total=max(total, 1),
            completed=completed,
            complete_style="cyan",
            finished_style="bold green",
        )
        info = Text()
        info.append(f"{completed}/{total}", style="bold")
        info.append(f" ({pct:.0f}%)", style="dim")
        for status, label in self._PROGRESS_STAT_ORDER:
            count = self._status_counts.get(status, 0)
            if not count:
                continue
            info.append("  ")
            style = STATUS_STYLES[status]
            info.append(f"{style.symbol} {count} {label}", style=style.color)
        content = Table.grid()
        content.add_column(ratio=1)
        content.add_row(bar)
        content.add_row(info)
        progress = Panel(
            content,
            title="Running tests...",
            title_align="left",
            border_style="green" if finished else "cyan",
            padding=(0, 1),
        )
        return Group(progress, live)

    def _top_level_key(self, item: LoadedTestDef) -> int:
        return item.spec.collection_index

    def is_top_level_definition(self, item: LoadedTestDef) -> bool:
        """Return whether the definition is a collected top-level item."""
        return (
            self._top_level_key(item) in self.item_keys
            and item.spec.suffix is None
            and item.spec.case_id is None
        )

    # ── Run event hooks ───────────────────────────────────────────────────────

    async def on_no_tests_found(self, run: ExecutedRun) -> None:
        """Print the empty-run message."""
        _ = run
        self.console.print("[yellow]No tests found.[/yellow]")

    async def on_collection_complete(
        self, items: list[LoadedTestDef], run: ExecutedRun
    ) -> None:
        """Initialize display state after collection."""
        if self._live is not None:
            self._live.stop()
            self._live = None
        self.items = list(items)
        self.item_keys = {self._top_level_key(item) for item in items}
        self.items_by_file = {}
        for item in items:
            self.items_by_file.setdefault(
                item.spec.locator.module_path, []
            ).append(item)
        self.total_tests = len(items)
        self.completed_count = 0
        self.tests = {}
        self.executions = {}
        self.all_executions = {}
        self.failures = []
        self._status_counts = {}
        self.current_module = None
        self.completed_modules = set()

        self.console.print(self._build_run_header(run))
        self.console.print()
        if self._mode.show_collected_count:
            self.console.print(
                f"Collected [bold cyan]{len(items)}[/bold cyan] tests\n"
            )

        if self.console.is_terminal:
            self._live = Live(
                self._build_live_display(),
                console=self.console,
                auto_refresh=True,
                refresh_per_second=1,
                transient=False,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self._live.start()
        self._stderr_capture.start()

    async def on_tests_ready(
        self, tests: list[ExecutableTest], run: ExecutedRun
    ) -> None:
        """Cache top-level executable tests for rendering."""
        _ = run
        for test in tests:
            if self.is_top_level_definition(test.definition):
                self.tests[self._top_level_key(test.definition)] = test

    async def on_test_start(
        self, test: ExecutableTest, run: ExecutedRun
    ) -> None:
        """Refresh live output before a test starts."""
        _ = test, run
        if self._live is not None:
            self._live.update(self._build_live_display(), refresh=True)

    async def on_execution_complete(
        self, execution: ExecutedTest, run: ExecutedRun
    ) -> None:
        """Record and render one completed execution."""
        _ = run
        async with self._lock:
            self.all_executions[id(execution.definition)] = execution

            is_top_level = self.is_top_level_definition(execution.definition)
            if is_top_level:
                self.executions[self._top_level_key(execution.definition)] = (
                    execution
                )
                self.completed_count += 1
                status = execution.result.status
                self._status_counts[status] = (
                    self._status_counts.get(status, 0) + 1
                )
                if status.is_failure:
                    self.failures.append(execution)

            if self._live is not None:
                module_path = execution.definition.spec.locator.module_path
                if module_path not in self.completed_modules and all(
                    self._top_level_key(i) in self.executions
                    for i in self.items_by_file.get(module_path, [])
                ):
                    self._mode.print_completed_module(
                        module_path, self.items_by_file[module_path], self
                    )
                    self.completed_modules.add(module_path)
                self._live.update(self._build_live_display(), refresh=True)
                return

            if not is_top_level:
                return

            self._mode.print_test(execution, self)

    async def on_run_complete(self, run: ExecutedRun) -> None:
        """Render the final run summary."""
        self._stderr_capture.stop()

        if self._live is not None:
            self._live.stop()
            self._live = None

        if self.verbosity == 0 and self.current_module is not None:
            self.console.print()

        if self._mode.show_failures and self.failures:
            for renderable in ConsoleExecutionView.render_assertion_failures(
                self.failures, self.verbosity
            ):
                self.console.print(renderable)
            for renderable in ConsoleExecutionView.render_exception_failures(
                self.failures,
                self.verbosity,
                show_locals=self.verbosity >= 2,
            ):
                self.console.print(renderable)

        if run.result.stopped_early:
            self.console.print("[yellow]Run terminated early.[/yellow]")

        if run.result.metric_results:
            metrics = ConsoleMetricRunView.from_results(
                run.result.metric_results
            )
            for renderable in metrics.render(self.verbosity):
                self.console.print(renderable)

        if self.verbosity >= 2:
            captured = ConsoleCapturedOutputView.from_lines(
                self._stderr_capture.lines
            )
            for renderable in captured.render():
                self.console.print(renderable)

        self.console.print()
        self.console.print(self._build_summary(run))

    async def on_run_stopped_early(
        self, failure_count: int, run: ExecutedRun
    ) -> None:
        """Print maxfail early-stop notice."""
        _ = run
        self.console.print(
            f"\n\n[red]Stopping early after {failure_count} failure(s).[/red]"
        )
