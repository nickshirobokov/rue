"""Terminal live-rendering session management."""

from __future__ import annotations

import asyncio
import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from os import devnull
from typing import TYPE_CHECKING

from rich.console import Console, RenderableType
from rich.live import Live

from rue.cli.rendering.experiments import (
    ExperimentLiveRenderer,
    ExperimentSuiteState,
)
from rue.cli.rendering.live import SuiteLiveRenderer
from rue.cli.rendering.metrics import MetricSuiteView
from rue.cli.rendering.state import TerminalSuiteState
from rue.cli.rendering.suite import SuiteView, TestExecutionView
from rue.context.runtime import SUITE_EXECUTION_CONTEXT
from rue.events import SuiteEventsProcessor
from rue.testing.execution.test.models import TestStatus


if TYPE_CHECKING:
    from rue.config import Config
    from rue.testing.execution.suite.models import ExecutedSuite
    from rue.testing.execution.test.base import ExecutableTest
    from rue.testing.execution.test.models import ExecutedTest, LoadedTestDef


class TerminalLiveSession:
    """Own Rich Live lifecycle and stdout/stderr suppression for terminals."""

    def __init__(
        self,
        console: Console,
        *,
        refresh_per_second: float,
    ) -> None:
        self.console = console
        self.refresh_per_second = refresh_per_second
        self._live: Live | None = None
        self._suppression = ExitStack()

    @property
    def is_active(self) -> bool:
        """Return whether a Rich Live session is running."""
        return self._live is not None

    def start(self, renderable: RenderableType) -> bool:
        """Start terminal live rendering if the console supports it."""
        if self._live is not None:
            self.update(renderable)
            return True
        if not self.console.is_terminal:
            return False

        # Rich Live owns screen refresh; raw writes would corrupt the frame.
        sink = self._suppression.enter_context(open(devnull, "w"))
        self._suppression.enter_context(redirect_stdout(sink))
        self._suppression.enter_context(redirect_stderr(sink))
        self._live = Live(
            renderable,
            console=self.console,
            auto_refresh=True,
            refresh_per_second=self.refresh_per_second,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self._live.start()
        return True

    def update(
        self,
        renderable: RenderableType,
        *,
        refresh: bool = True,
    ) -> None:
        """Refresh the live view when a session is active."""
        if self._live is not None:
            self._live.update(renderable, refresh=refresh)

    def close(self) -> None:
        """Stop live rendering and restore stdout/stderr."""
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._suppression.close()
        self._suppression = ExitStack()


class TerminalSuiteReporter(SuiteEventsProcessor):
    """Translate single-suite lifecycle events into terminal rendering updates."""

    def __init__(
        self, console: Console | None = None, verbosity: int = 0
    ) -> None:
        self.console = console or Console(file=sys.__stdout__)
        self.verbosity = verbosity
        self._renderer = SuiteLiveRenderer(self.console, verbosity)
        self._live = TerminalLiveSession(
            self.console,
            refresh_per_second=1,
        )
        self._lock = asyncio.Lock()
        self.state = TerminalSuiteState(verbosity=verbosity)

    def configure(self, config: Config) -> None:
        """Apply runtime terminal settings."""
        self.verbosity = config.verbosity
        self.state.configure(self.verbosity)
        self._renderer.configure(self.verbosity)

    def close(self) -> None:
        """Release terminal resources."""
        self._live.close()

    async def on_no_tests_found(self, suite: ExecutedSuite) -> None:
        """Print the empty-suite message."""
        _ = suite
        self.console.print("[yellow]No tests found.[/yellow]")

    async def on_collection_complete(
        self, items: list[LoadedTestDef], suite: ExecutedSuite
    ) -> None:
        """Initialize display state after collection."""
        self.state.reset_collection(items)

        self.console.print(SuiteView.from_suite(suite).render_header())
        self.console.print()
        if self._renderer.show_collected_count:
            self.console.print(
                f"Collected [bold cyan]{len(items)}[/bold cyan] tests\n"
            )

        self._live.start(self._renderer.render(self.state))

    async def on_tests_ready(
        self, tests: list[ExecutableTest], suite: ExecutedSuite
    ) -> None:
        """Cache top-level executable tests for rendering."""
        _ = suite
        self.state.record_ready_tests(tests)

    async def on_test_execution_start(
        self, test: ExecutableTest, suite: ExecutedSuite
    ) -> None:
        """Refresh live output before test execution starts."""
        _ = test, suite
        if self._live.is_active:
            self._live.update(self._renderer.render(self.state), refresh=True)

    async def on_test_execution_complete(
        self, execution: ExecutedTest, suite: ExecutedSuite
    ) -> None:
        """Record and render one completed test execution."""
        _ = suite
        async with self._lock:
            is_top_level = self.state.record_test_execution(execution)

            if self._live.is_active:
                module_path = execution.definition.spec.locator.module_path
                # Completed modules print once before leaving the live view.
                if (
                    module_path not in self.state.completed_modules
                    and self.state.is_module_complete(module_path)
                ):
                    self._renderer.print_completed_module(
                        module_path,
                        self.state.items_by_file[module_path],
                        self.state,
                    )
                    self.state.mark_module_completed(module_path)
                self._live.update(
                    self._renderer.render(self.state), refresh=True
                )
                return

            if not is_top_level:
                return

            self._renderer.print_test(execution, self.state)

    async def on_suite_execution_complete(self, suite: ExecutedSuite) -> None:
        """Render the final suite summary."""
        self._live.close()

        if self.verbosity == 0 and self.state.current_module is not None:
            self.console.print()

        if self._renderer.show_failures and self.state.failures:
            for renderable in TestExecutionView.render_assertion_failures(
                self.state.failures, self.verbosity
            ):
                self.console.print(renderable)
            for renderable in TestExecutionView.render_exception_failures(
                self.state.failures,
                self.verbosity,
                show_locals=self.verbosity >= 2,
            ):
                self.console.print(renderable)

        if suite.result.stopped_early:
            self.console.print("[yellow]Suite terminated early.[/yellow]")

        if suite.result.metric_results:
            metrics = MetricSuiteView.from_results(
                suite.result.metric_results
            )
            for renderable in metrics.render(self.verbosity):
                self.console.print(renderable)

        self.console.print()
        self.console.print(SuiteView.from_suite(suite).render_summary())

    async def on_suite_stopped_early(
        self, failure_count: int, suite: ExecutedSuite
    ) -> None:
        """Print maxfail early-stop notice."""
        _ = suite
        self.console.print(
            f"\n\n[red]Stopping early after {failure_count} failure(s).[/red]"
        )


class TerminalExperimentReporter(SuiteEventsProcessor):
    """Translate multi-suite experiment session events into terminal updates."""

    def __init__(
        self, console: Console | None = None, verbosity: int = 0
    ) -> None:
        self.console = console or Console(file=sys.__stdout__)
        self.verbosity = verbosity
        self._live = TerminalLiveSession(
            self.console,
            refresh_per_second=2,
        )
        self._renderer = ExperimentLiveRenderer(verbosity=verbosity)
        self._lock = asyncio.Lock()

    def configure(self, config: Config) -> None:
        """Apply runtime terminal settings."""
        self.verbosity = config.verbosity
        self._renderer.configure(config.verbosity)

    def close(self) -> None:
        """Release terminal resources."""
        self._live.close()

    async def on_suite_execution_start(self, suite: ExecutedSuite) -> None:
        """Start tracking an experiment variant suite."""
        variant = SUITE_EXECUTION_CONTEXT.get().experiment_variant
        label = "suite" if variant is None else variant.label
        async with self._lock:
            self._renderer.states[suite.suite_execution_id] = ExperimentSuiteState(
                label=label,
                suite_execution_id=suite.suite_execution_id,
            )
            self._refresh()

    async def on_no_tests_found(self, suite: ExecutedSuite) -> None:
        """Mark a variant with no tests."""
        async with self._lock:
            state = self._renderer.states[suite.suite_execution_id]
            state.phase = "no tests"
            self._refresh()

    async def on_collection_complete(
        self, items: list[LoadedTestDef], suite: ExecutedSuite
    ) -> None:
        """Record variant collection size."""
        async with self._lock:
            state = self._renderer.states[suite.suite_execution_id]
            state.item_keys = {
                item.spec.collection_index for item in items
            }
            state.total_tests = len(items)
            state.phase = "collected"
            self._refresh()

    async def on_tests_ready(
        self, tests: list[ExecutableTest], suite: ExecutedSuite
    ) -> None:
        """Record executable test readiness."""
        async with self._lock:
            state = self._renderer.states[suite.suite_execution_id]
            state.ready_tests = len(tests)
            state.phase = "ready"
            self._refresh()

    async def on_test_execution_start(
        self, test: ExecutableTest, suite: ExecutedSuite
    ) -> None:
        """Record a started test execution."""
        _ = test
        async with self._lock:
            state = self._renderer.states[suite.suite_execution_id]
            state.started_count += 1
            state.phase = "running"
            self._refresh()

    async def on_test_execution_complete(
        self, execution: ExecutedTest, suite: ExecutedSuite
    ) -> None:
        """Record one completed top-level test execution."""
        async with self._lock:
            state = self._renderer.states[suite.suite_execution_id]
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

    async def on_suite_stopped_early(
        self, failure_count: int, suite: ExecutedSuite
    ) -> None:
        """Mark a variant stopped by maxfail."""
        _ = failure_count
        async with self._lock:
            state = self._renderer.states[suite.suite_execution_id]
            state.stopped_early = True
            state.phase = "stopping"
            self._refresh()

    async def on_suite_execution_complete(self, suite: ExecutedSuite) -> None:
        """Render completed variant state."""
        async with self._lock:
            state = self._renderer.states[suite.suite_execution_id]
            state.completed_count = suite.result.total
            state.duration_ms = suite.result.total_duration_ms
            state.stopped_early = suite.result.stopped_early
            state.status_counts = {
                TestStatus.PASSED: suite.result.passed,
                TestStatus.FAILED: suite.result.failed,
                TestStatus.ERROR: suite.result.errors,
                TestStatus.SKIPPED: suite.result.skipped,
                TestStatus.XFAILED: suite.result.xfailed,
                TestStatus.XPASSED: suite.result.xpassed,
            }
            state.phase = "stopped" if state.stopped_early else "complete"
            self._refresh()
            if not self._live.is_active:
                self.console.print(self._renderer.completed_line(state))

    def _refresh(self) -> None:
        self._live.start(self._renderer.render())


__all__ = [
    "TerminalExperimentReporter",
    "TerminalLiveSession",
    "TerminalSuiteReporter",
]
