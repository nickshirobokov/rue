"""ConsoleReporter: slim orchestrator delegating to focused sub-components."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from rue.reports.base import Reporter

from .assertions import AssertionRenderer
from .captured import CapturedOutputRenderer, StderrCapture
from .failures import ExceptionRenderer
from .metrics import MetricsRenderer
from .modes import OutputMode, make_mode
from .shared import STATUS_STYLES

from rue.testing.models import TestStatus

if TYPE_CHECKING:
    from rue.config import Config
    from rue.testing import TestDefinition
    from rue.testing.execution.interfaces import Test
    from rue.testing.models.result import TestExecution
    from rue.testing.models.run import Run, RunEnvironment


class ConsoleReporter(Reporter):
    _PROGRESS_STAT_ORDER: tuple[tuple[TestStatus, str], ...] = (
        (TestStatus.PASSED, "passed"),
        (TestStatus.FAILED, "failed"),
        (TestStatus.ERROR, "errors"),
        (TestStatus.SKIPPED, "skipped"),
        (TestStatus.XFAILED, "xfailed"),
        (TestStatus.XPASSED, "xpassed"),
    )

    def __init__(self, console: Console | None = None, verbosity: int = 0) -> None:
        self.console = console or Console(file=sys.__stdout__)
        self.verbosity = verbosity
        self._mode: OutputMode = make_mode(verbosity, self.console)
        self._live: Live | None = None
        self._assertions = AssertionRenderer()
        self._exceptions = ExceptionRenderer()
        self._metrics = MetricsRenderer()
        self._stderr_capture = StderrCapture()
        self._captured_renderer = CapturedOutputRenderer()
        self._lock = asyncio.Lock()
        self.items: list[TestDefinition] = []
        self.item_ids: set[int] = set()
        self.items_by_file: dict[Path, list[TestDefinition]] = {}
        self.total_tests: int = 0
        self.completed_count: int = 0
        self.tests: dict[int, Test] = {}
        self.executions: dict[int, TestExecution] = {}
        self.failures: list[TestExecution] = []
        self._status_counts: dict[TestStatus, int] = {}
        self.current_module: Path | None = None
        self.completed_modules: set[Path] = set()

    def configure(self, config: Config) -> None:
        self.verbosity = config.verbosity
        self._mode = make_mode(self.verbosity, self.console)
        self._assertions = AssertionRenderer()
        self._exceptions = ExceptionRenderer(show_locals=config.verbosity >= 2)

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

    def _build_live_display(self) -> RenderableType:
        if self.items_by_file and len(self.completed_modules) == len(self.items_by_file):
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

    # ── Reporter hooks ────────────────────────────────────────────────────────

    async def on_no_tests_found(self) -> None:
        self.console.print("[yellow]No tests found.[/yellow]")

    async def on_collection_complete(
        self, items: list[TestDefinition], run: Run
    ) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
        self.items = list(items)
        self.item_ids = {id(item) for item in items}
        self.items_by_file = {}
        for item in items:
            self.items_by_file.setdefault(item.spec.module_path, []).append(item)
        self.total_tests = len(items)
        self.completed_count = 0
        self.tests = {}
        self.executions = {}
        self.failures = []
        self._status_counts = {}
        self.current_module = None
        self.completed_modules = set()

        self.console.print(self._build_run_header(run.environment, run.run_id))
        self.console.print()
        if self._mode.show_collected_count:
            self.console.print(f"[bold]Collected {len(items)} tests[/bold]\n")

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

    async def on_tests_ready(self, tests: list[Test]) -> None:
        for test in tests:
            self.tests[id(test.definition)] = test

    async def on_test_start(self, item: TestDefinition) -> None:
        if self._live is not None:
            self._live.update(self._build_live_display(), refresh=True)

    async def on_execution_complete(self, execution: TestExecution) -> None:
        async with self._lock:
            self.executions[id(execution.definition)] = execution

            is_top_level = id(execution.definition) in self.item_ids
            if is_top_level:
                self.completed_count += 1
                status = execution.result.status
                self._status_counts[status] = self._status_counts.get(status, 0) + 1
                if status.is_failure:
                    self.failures.append(execution)

            if self._live is not None:
                module_path = execution.definition.spec.module_path
                if (
                    module_path not in self.completed_modules
                    and all(id(i) in self.executions for i in self.items_by_file.get(module_path, []))
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

    async def on_run_complete(self, run: Run) -> None:
        self._stderr_capture.stop()

        if self._live is not None:
            self._live.stop()
            self._live = None

        if self.verbosity == 0 and self.current_module is not None:
            self.console.print()

        if self._mode.show_failures and self.failures:
            for renderable in self._assertions.render(self.failures):
                self.console.print(renderable)
            for renderable in self._exceptions.render(self.failures):
                self.console.print(renderable)

        if run.result.stopped_early:
            self.console.print("[yellow]Run terminated early.[/yellow]")

        for renderable in self._metrics.render(
            run.result.metric_results,
            self.verbosity,
            run.result.executions,
        ):
            self.console.print(renderable)

        if self.verbosity >= 2:
            for renderable in self._captured_renderer.render(self._stderr_capture.lines):
                self.console.print(renderable)

        self.console.print()
        self.console.print(self._build_summary(run))

    async def on_run_stopped_early(self, failure_count: int) -> None:
        self.console.print(
            f"\n\n[red]Stopping early after {failure_count} failure(s).[/red]"
        )
