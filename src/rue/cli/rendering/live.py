"""Live suite output rendering."""

# ruff: noqa: D102

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from rue.cli.rendering.primitives import STATUS_STYLES
from rue.cli.rendering.state import TerminalSuiteState
from rue.cli.rendering.suite import TestExecutionView
from rue.cli.rendering.tests import TestModuleView
from rue.testing.execution.models import TestStatus
from rue.testing.execution.test.composite import CompositeTest


if TYPE_CHECKING:
    from pathlib import Path

    from rue.testing.execution.models import ExecutedTest, LoadedTestDef


_PROGRESS_STAT_ORDER: tuple[tuple[TestStatus, str], ...] = (
    (TestStatus.PASSED, "passed"),
    (TestStatus.FAILED, "failed"),
    (TestStatus.ERROR, "errors"),
    (TestStatus.SKIPPED, "skipped"),
    (TestStatus.NOT_RUN, "not run"),
    (TestStatus.XFAILED, "xfailed"),
    (TestStatus.XPASSED, "xpassed"),
)


class SuiteLiveRenderer:
    """Render live suite progress for the selected verbosity."""

    def __init__(
        self, console: Console, verbosity: int = 0
    ) -> None:
        self.console = console
        self.verbosity = verbosity
        self.mode: OutputMode = make_mode(verbosity, console)

    @property
    def show_collected_count(self) -> bool:
        return self.mode.show_collected_count

    @property
    def show_failures(self) -> bool:
        return self.mode.show_failures

    def configure(self, verbosity: int) -> None:
        self.verbosity = verbosity
        self.mode = make_mode(verbosity, self.console)

    def render(self, state: TerminalSuiteState) -> RenderableType:
        """Return the current live renderable for terminal refresh."""
        if state.all_modules_complete:
            return Text("")
        live = self.mode.render_live(state)
        if not self.mode.show_progress_bar:
            return live
        return Group(self._progress_panel(state), live)

    def print_completed_module(
        self,
        path: Path,
        items: list[LoadedTestDef],
        state: TerminalSuiteState,
    ) -> None:
        self.mode.print_completed_module(path, items, state)

    def print_test(
        self,
        execution: ExecutedTest,
        state: TerminalSuiteState,
    ) -> None:
        self.mode.print_test(execution, state)

    def _progress_panel(self, state: TerminalSuiteState) -> Panel:
        completed = state.completed_count
        total = state.total_tests
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
        for status, label in _PROGRESS_STAT_ORDER:
            count = state.status_counts.get(status, 0)
            if not count:
                continue
            info.append("  ")
            style = STATUS_STYLES[status]
            info.append(f"{style.symbol} {count} {label}", style=style.color)
        content = Table.grid()
        content.add_column(ratio=1)
        content.add_row(bar)
        content.add_row(info)
        return Panel(
            content,
            title="Running tests...",
            title_align="left",
            border_style="green" if finished else "cyan",
            padding=(0, 1),
        )


class OutputMode(ABC):
    """Verbosity-specific strategy for live and non-live suite output."""

    def __init__(self, console: Console) -> None:
        self.console = console

    @property
    def show_failures(self) -> bool:
        return False

    @property
    def show_collected_count(self) -> bool:
        return True

    @property
    def show_progress_bar(self) -> bool:
        return False

    def _render_spinner_line(self, text: Text) -> Table:
        line = Table.grid(padding=(0, 1))
        line.add_column()
        line.add_column(no_wrap=True)
        line.add_row(text, Spinner("simpleDots", style="bold blue"))
        return line

    @abstractmethod
    def render_live(self, state: TerminalSuiteState) -> RenderableType: ...

    @abstractmethod
    def print_test(
        self, execution: ExecutedTest, state: TerminalSuiteState
    ) -> None: ...

    def print_completed_module(
        self,
        path: Path,
        items: list[LoadedTestDef],
        state: TerminalSuiteState,
    ) -> None:
        for item in items:
            execution = state.test_executions.get(item.spec.collection_index)
            if execution is not None:
                self.print_test(execution, state)


class QuietMode(OutputMode):
    """Show only aggregate progress for `-q` output."""

    @property
    def show_collected_count(self) -> bool:
        return False

    def render_live(self, state: TerminalSuiteState) -> RenderableType:
        progress = f"{state.completed_count}/{state.total_tests}"
        text = Text.from_markup(
            f"Running tests... {progress} completed"
        )
        return self._render_spinner_line(text)

    def print_test(
        self, execution: ExecutedTest, state: TerminalSuiteState
    ) -> None:
        pass


class CompactMode(OutputMode):
    """Print pytest-style compact module symbols at default verbosity."""

    def render_live(self, state: TerminalSuiteState) -> RenderableType:
        lines: list[RenderableType] = []
        for path, items in state.items_by_file.items():
            if path in state.completed_modules:
                continue
            line = TestModuleView(path).compact_text()
            has_running = False
            for item in items:
                execution = state.test_executions.get(item.spec.collection_index)
                if execution is None:
                    has_running = True
                    line.append("⋯", style="dim")
                    continue
                style = STATUS_STYLES[execution.result.status]
                line.append(style.symbol, style=style.color)
            lines.append(
                self._render_spinner_line(line) if has_running else line
            )
        return Group(*lines) if lines else Text("")

    def print_test(
        self, execution: ExecutedTest, state: TerminalSuiteState
    ) -> None:
        definition = execution.definition
        style = STATUS_STYLES[execution.result.status]
        if state.current_module != definition.spec.locator.module_path:
            if state.current_module is not None:
                self.console.print()
            self.console.print(
                TestModuleView(
                    definition.spec.locator.module_path
                ).compact_text(),
                end="",
            )
            state.current_module = definition.spec.locator.module_path
        self.console.print(Text(style.symbol, style=style.color), end="")

    def print_completed_module(
        self,
        path: Path,
        items: list[LoadedTestDef],
        state: TerminalSuiteState,
    ) -> None:
        line = TestModuleView(path).compact_text()
        for item in items:
            execution = state.test_executions.get(item.spec.collection_index)
            if execution is not None:
                style = STATUS_STYLES[execution.result.status]
                line.append(style.symbol, style=style.color)
        self.console.print(line)
        state.current_module = path


class VerboseMode(OutputMode):
    """Render expanded test trees and failure details for verbose output."""

    @property
    def show_failures(self) -> bool:
        return True

    @property
    def show_progress_bar(self) -> bool:
        return True

    def _iter_sub_test_executions(
        self,
        sub_test_executions: list[ExecutedTest],
        indent: int,
        verbosity: int,
    ) -> list[RenderableType]:
        renderables: list[RenderableType] = []
        for sub in sub_test_executions:
            if sub.result.status in {
                TestStatus.PASSED,
                TestStatus.FAILED,
                TestStatus.ERROR,
                TestStatus.NOT_RUN,
            }:
                view = TestExecutionView.from_test_execution(
                    sub, verbosity=verbosity
                )
                renderables.append(
                    view.render_test_line(indent=indent, sub=True)
                )
            if sub.sub_test_executions:
                renderables.extend(
                    self._iter_sub_test_executions(
                        sub.sub_test_executions, indent + 2, verbosity
                    )
                )
        return renderables

    def render_live(self, state: TerminalSuiteState) -> RenderableType:
        """Render unfinished modules with pending and completed nodes."""
        trees: list[Tree] = []
        for path, items in state.items_by_file.items():
            if path in state.completed_modules:
                continue
            tree = Tree(TestModuleView(path).tree_text())
            for item in items:
                key = item.spec.collection_index
                test = state.tests.get(key)
                execution = state.test_executions.get(key)
                branch = tree.add(self._build_live_item_line(item, execution))
                if execution is not None and execution.sub_test_executions:
                    self._add_live_sub_test_executions(
                        branch, execution.sub_test_executions, state
                    )
                elif (
                    execution is None
                    and isinstance(test, CompositeTest)
                ):
                    # Composite tests can reveal completed children early.
                    self._add_live_composite_children(branch, test, state)
                elif execution is None:
                    early = self._early_sub_test_executions(item, state)
                    if early:
                        self._add_live_sub_test_executions(branch, early, state)
            trees.append(tree)
        return Group(*trees) if trees else Text("")

    def _early_sub_test_executions(
        self, item: LoadedTestDef, state: TerminalSuiteState
    ) -> list[ExecutedTest]:
        """Child test executions that completed before the parent finished."""
        return [
            ex
            for ex in state.all_test_executions.values()
            if (
                ex.definition.spec.collection_index
                == item.spec.collection_index
                and not state.is_top_level_definition(ex.definition)
            )
        ]

    def print_completed_module(
        self,
        path: Path,
        items: list[LoadedTestDef],
        state: TerminalSuiteState,
    ) -> None:
        tree = Tree(TestModuleView(path).tree_text())
        for item in items:
            execution = state.test_executions.get(item.spec.collection_index)
            branch = tree.add(self._build_live_item_line(item, execution))
            if execution is not None and execution.sub_test_executions:
                self._add_live_sub_test_executions(
                    branch, execution.sub_test_executions, state
                )
        self.console.print(tree)
        state.current_module = path

    def print_test(
        self, execution: ExecutedTest, state: TerminalSuiteState
    ) -> None:
        definition = execution.definition
        if state.current_module != definition.spec.locator.module_path:
            if state.current_module is not None:
                self.console.print(Text(""))
            self.console.print(
                TestModuleView(
                    definition.spec.locator.module_path
                ).tree_text()
            )
            state.current_module = definition.spec.locator.module_path

        view = TestExecutionView.from_test_execution(
            execution, verbosity=state.verbosity
        )
        if execution.sub_test_executions:
            self.console.print(
                view.render_test_line(name=definition.spec.local_name)
            )
            for renderable in self._iter_sub_test_executions(
                execution.sub_test_executions,
                indent=4,
                verbosity=state.verbosity,
            ):
                self.console.print(renderable)
        else:
            self.console.print(
                view.render_test_line(
                    name=definition.spec.local_name,
                    extra=execution.result.status_repr,
                )
            )

    def _build_live_item_line(
        self,
        item: LoadedTestDef,
        execution: ExecutedTest | None,
    ) -> RenderableType:
        if execution is None:
            return self._render_spinner_line(
                TestExecutionView.running_line(item.spec.local_name)
            )
        view = TestExecutionView.from_test_execution(execution)
        return view.render_live_item_line(name=item.spec.local_name)

    def _add_live_composite_children(
        self, parent: Tree, test: CompositeTest, state: TerminalSuiteState
    ) -> None:
        for child in test.children:
            child_exec = state.all_test_executions.get(id(child.definition))
            if child_exec is not None:
                parent.add(
                    self._render_sub_live_line(
                        child_exec,
                        verbosity=state.verbosity,
                    )
                )
                if child_exec.sub_test_executions:
                    self._add_live_sub_test_executions(
                        parent.children[-1],
                        child_exec.sub_test_executions,
                        state,
                    )
            elif isinstance(child, CompositeTest):
                pending_label = (
                    child.definition.spec.get_label(
                        full=state.verbosity >= 2
                    )
                )
                pending = TestExecutionView.sub_label_text(
                    pending_label or "case"
                )
                pending.append("  ⋯", style="dim")
                node = parent.add(pending)
                self._add_live_composite_children(node, child, state)

    def _add_live_sub_test_executions(
        self,
        parent: Tree,
        sub_test_executions: list[ExecutedTest],
        state: TerminalSuiteState,
    ) -> None:
        for sub in sub_test_executions:
            node = parent
            if sub.result.status in {
                TestStatus.PASSED,
                TestStatus.FAILED,
                TestStatus.ERROR,
                TestStatus.NOT_RUN,
            }:
                node = parent.add(
                    self._render_sub_live_line(
                        sub, verbosity=state.verbosity
                    )
            )
            if sub.sub_test_executions:
                self._add_live_sub_test_executions(
                    node,
                    sub.sub_test_executions,
                    state,
                )

    def _render_sub_live_line(
        self, execution: ExecutedTest, *, verbosity: int
    ) -> Text:
        view = TestExecutionView.from_test_execution(
            execution, verbosity=verbosity
        )
        return view.render_sub_live_line()


def make_mode(verbosity: int, console: Console) -> OutputMode:
    """Select the output strategy matching CLI verbosity."""
    if verbosity < 0:
        return QuietMode(console)
    if verbosity == 0:
        return CompactMode(console)
    return VerboseMode(console)


__all__ = [
    "CompactMode",
    "OutputMode",
    "QuietMode",
    "SuiteLiveRenderer",
    "VerboseMode",
    "make_mode",
]
