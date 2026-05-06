"""ConsoleReporter: Rich console processor for Rue test runs."""

from __future__ import annotations

import asyncio
import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from os import devnull
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from rue.context.runtime import CURRENT_RUN_CONTEXT
from rue.events import RunEventsProcessor
from rue.testing.models import TestStatus

from .modes import OutputMode, make_mode
from .shared import STATUS_STYLES
from .views import (
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


@dataclass
class _ExperimentRunState:
    label: str
    run_id: UUID
    item_keys: set[int] = field(default_factory=set)
    total_tests: int = 0
    ready_tests: int = 0
    started_count: int = 0
    completed_count: int = 0
    status_counts: dict[TestStatus, int] = field(default_factory=dict)
    phase: str = "starting"
    duration_ms: float = 0
    stopped_early: bool = False


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
        self._output_suppression = ExitStack()
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

    def close(self) -> None:
        """Release console resources."""
        if self._live is not None:
            self._live.stop()
        self._output_suppression.close()

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

    def is_top_level_definition(self, item: LoadedTestDef) -> bool:
        """Return whether the definition is a collected top-level item."""
        return (
            item.spec.collection_index in self.item_keys
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
        self.items = list(items)
        self.item_keys = {item.spec.collection_index for item in items}
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

        self.console.print(ConsoleRunView.from_run(run).render_header())
        self.console.print()
        if self._mode.show_collected_count:
            self.console.print(
                f"Collected [bold cyan]{len(items)}[/bold cyan] tests\n"
            )

        if self.console.is_terminal:
            sink = self._output_suppression.enter_context(open(devnull, "w"))
            self._output_suppression.enter_context(redirect_stdout(sink))
            self._output_suppression.enter_context(redirect_stderr(sink))
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

    async def on_tests_ready(
        self, tests: list[ExecutableTest], run: ExecutedRun
    ) -> None:
        """Cache top-level executable tests for rendering."""
        _ = run
        for test in tests:
            if self.is_top_level_definition(test.definition):
                self.tests[test.definition.spec.collection_index] = test

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
                self.executions[execution.definition.spec.collection_index] = (
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
                    i.spec.collection_index in self.executions
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
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._output_suppression.close()

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

        self.console.print()
        self.console.print(ConsoleRunView.from_run(run).render_summary())

    async def on_run_stopped_early(
        self, failure_count: int, run: ExecutedRun
    ) -> None:
        """Print maxfail early-stop notice."""
        _ = run
        self.console.print(
            f"\n\n[red]Stopping early after {failure_count} failure(s).[/red]"
        )


class ExperimentConsoleReporter(RunEventsProcessor):
    """Rich console processor for experiment sessions."""

    _STATUS_ORDER: tuple[TestStatus, ...] = (
        TestStatus.PASSED,
        TestStatus.FAILED,
        TestStatus.ERROR,
        TestStatus.SKIPPED,
        TestStatus.XFAILED,
        TestStatus.XPASSED,
    )

    def __init__(
        self, console: Console | None = None, verbosity: int = 0
    ) -> None:
        self.console = console or Console(file=sys.__stdout__)
        self.verbosity = verbosity
        self._live: Live | None = None
        self._states: dict[UUID, _ExperimentRunState] = {}
        self._lock = asyncio.Lock()

    def configure(self, config: Config) -> None:
        """Apply runtime console settings."""
        self.verbosity = config.verbosity

    def close(self) -> None:
        """Release console resources."""
        if self._live is not None:
            self._live.stop()
            self._live = None

    async def on_run_start(self, run: ExecutedRun) -> None:
        """Start tracking an experiment variant run."""
        variant = CURRENT_RUN_CONTEXT.get().experiment_variant
        label = "run" if variant is None else variant.label
        async with self._lock:
            self._states[run.run_id] = _ExperimentRunState(
                label=label,
                run_id=run.run_id,
            )
            self._refresh()

    async def on_no_tests_found(self, run: ExecutedRun) -> None:
        """Mark a variant with no tests."""
        async with self._lock:
            state = self._states[run.run_id]
            state.phase = "no tests"
            self._refresh()

    async def on_collection_complete(
        self, items: list[LoadedTestDef], run: ExecutedRun
    ) -> None:
        """Record variant collection size."""
        async with self._lock:
            state = self._states[run.run_id]
            state.item_keys = {
                item.spec.collection_index for item in items
            }
            state.total_tests = len(items)
            state.phase = "collected"
            self._refresh()

    async def on_tests_ready(
        self, tests: list[ExecutableTest], run: ExecutedRun
    ) -> None:
        """Record executable test readiness."""
        async with self._lock:
            state = self._states[run.run_id]
            state.ready_tests = len(tests)
            state.phase = "ready"
            self._refresh()

    async def on_test_start(
        self, test: ExecutableTest, run: ExecutedRun
    ) -> None:
        """Record a started test."""
        _ = test
        async with self._lock:
            state = self._states[run.run_id]
            state.started_count += 1
            state.phase = "running"
            self._refresh()

    async def on_execution_complete(
        self, execution: ExecutedTest, run: ExecutedRun
    ) -> None:
        """Record one completed top-level execution."""
        async with self._lock:
            state = self._states[run.run_id]
            spec = execution.definition.spec
            if (
                spec.collection_index in state.item_keys
                and spec.suffix is None
                and spec.case_id is None
            ):
                state.completed_count += 1
                status = execution.result.status
                state.status_counts[status] = (
                    state.status_counts.get(status, 0) + 1
                )
            state.phase = "running"
            self._refresh()

    async def on_run_stopped_early(
        self, failure_count: int, run: ExecutedRun
    ) -> None:
        """Mark a variant stopped by maxfail."""
        _ = failure_count
        async with self._lock:
            state = self._states[run.run_id]
            state.stopped_early = True
            state.phase = "stopping"
            self._refresh()

    async def on_run_complete(self, run: ExecutedRun) -> None:
        """Render completed variant state."""
        async with self._lock:
            state = self._states[run.run_id]
            state.completed_count = run.result.total
            state.duration_ms = run.result.total_duration_ms
            state.stopped_early = run.result.stopped_early
            state.status_counts = {
                TestStatus.PASSED: run.result.passed,
                TestStatus.FAILED: run.result.failed,
                TestStatus.ERROR: run.result.errors,
                TestStatus.SKIPPED: run.result.skipped,
                TestStatus.XFAILED: run.result.xfailed,
                TestStatus.XPASSED: run.result.xpassed,
            }
            state.phase = "stopped" if state.stopped_early else "complete"
            self._refresh()
            if self._live is None:
                self.console.print(self._completed_line(state))

    def _refresh(self) -> None:
        if not self.console.is_terminal:
            return
        if self._live is None:
            self._live = Live(
                self._render_live_display(),
                console=self.console,
                auto_refresh=True,
                refresh_per_second=2,
                transient=False,
            )
            self._live.start()
            return
        self._live.update(self._render_live_display(), refresh=True)

    def _render_live_display(self) -> Panel:
        table = Table(show_header=True, expand=True)
        table.add_column("Variant")
        table.add_column("Run", no_wrap=True)
        table.add_column("Progress", justify="right", no_wrap=True)
        table.add_column("Status")
        table.add_column("Phase", no_wrap=True)
        table.add_column("Duration", justify="right", no_wrap=True)

        for state in self._states.values():
            table.add_row(
                state.label,
                str(state.run_id)[:8],
                self._progress_text(state),
                self._status_text(state),
                state.phase,
                self._duration_text(state),
            )

        return Panel(
            table,
            title="Running experiments...",
            title_align="left",
            border_style="cyan",
            padding=(0, 1),
        )

    def _completed_line(self, state: _ExperimentRunState) -> Text:
        text = Text()
        text.append(f"variant {state.label}: ", style="bold")
        text.append_text(self._status_text(state))
        duration = self._duration_text(state)
        if duration:
            text.append(f" in {duration}", style="dim")
        return text

    def _progress_text(self, state: _ExperimentRunState) -> str:
        total = state.total_tests
        if not total:
            return "0/0"
        return f"{state.completed_count}/{total}"

    def _status_text(self, state: _ExperimentRunState) -> Text:
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

    def _duration_text(self, state: _ExperimentRunState) -> str:
        if state.duration_ms <= 0:
            return ""
        return f"{state.duration_ms / 1000:.2f}s"
