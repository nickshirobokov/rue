"""Output mode strategy: QuietMode, CompactMode, VerboseMode."""

# ruff: noqa: D101,D102,D103

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from rue.testing.execution.composite import CompositeTest
from rue.testing.models import TestStatus

from .shared import STATUS_STYLES
from .views import ConsoleExecutionView, ConsoleModuleView


if TYPE_CHECKING:
    from pathlib import Path

    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.loaded import LoadedTestDef

    from .reporter import ConsoleReporter


class OutputMode(ABC):
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
    def render_live(self, state: ConsoleReporter) -> RenderableType: ...

    @abstractmethod
    def print_test(
        self, execution: ExecutedTest, state: ConsoleReporter
    ) -> None: ...

    def print_completed_module(
        self,
        path: Path | None,
        items: list[LoadedTestDef],
        state: ConsoleReporter,
    ) -> None:
        for item in items:
            execution = state.executions.get(item.spec.collection_index)
            if execution is not None:
                self.print_test(execution, state)


class QuietMode(OutputMode):
    @property
    def show_collected_count(self) -> bool:
        return False

    def render_live(self, state: ConsoleReporter) -> RenderableType:
        progress = f"{state.completed_count}/{state.total_tests}"
        text = Text.from_markup(
            f"Running tests... {progress} completed"
        )
        return self._render_spinner_line(text)

    def print_test(
        self, execution: ExecutedTest, state: ConsoleReporter
    ) -> None:
        pass


class CompactMode(OutputMode):
    def render_live(self, state: ConsoleReporter) -> RenderableType:
        lines: list[RenderableType] = []
        for path, items in state.items_by_file.items():
            if path in state.completed_modules:
                continue
            line = ConsoleModuleView(path).compact_text()
            has_running = False
            for item in items:
                execution = state.executions.get(item.spec.collection_index)
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
        self, execution: ExecutedTest, state: ConsoleReporter
    ) -> None:
        definition = execution.definition
        style = STATUS_STYLES[execution.result.status]
        if state.current_module != definition.spec.locator.module_path:
            if state.current_module is not None:
                self.console.print()
            self.console.print(
                ConsoleModuleView(
                    definition.spec.locator.module_path
                ).compact_text(),
                end="",
            )
            state.current_module = definition.spec.locator.module_path
        self.console.print(Text(style.symbol, style=style.color), end="")

    def print_completed_module(
        self,
        path: Path | None,
        items: list[LoadedTestDef],
        state: ConsoleReporter,
    ) -> None:
        line = ConsoleModuleView(path).compact_text()
        for item in items:
            execution = state.executions.get(item.spec.collection_index)
            if execution is not None:
                style = STATUS_STYLES[execution.result.status]
                line.append(style.symbol, style=style.color)
        self.console.print(line)
        state.current_module = path


class VerboseMode(OutputMode):
    @property
    def show_failures(self) -> bool:
        return True

    @property
    def show_progress_bar(self) -> bool:
        return True

    def _iter_sub_executions(
        self,
        sub_executions: list[ExecutedTest],
        indent: int,
        verbosity: int,
    ) -> list[RenderableType]:
        renderables: list[RenderableType] = []
        for sub in sub_executions:
            if sub.result.status in {
                TestStatus.PASSED,
                TestStatus.FAILED,
                TestStatus.ERROR,
            }:
                view = ConsoleExecutionView.from_execution(
                    sub, verbosity=verbosity
                )
                renderables.append(
                    view.render_test_line(indent=indent, sub=True)
                )
            if sub.sub_executions:
                renderables.extend(
                    self._iter_sub_executions(
                        sub.sub_executions, indent + 2, verbosity
                    )
                )
        return renderables

    def render_live(self, state: ConsoleReporter) -> RenderableType:
        trees: list[Tree] = []
        for path, items in state.items_by_file.items():
            if path in state.completed_modules:
                continue
            tree = Tree(ConsoleModuleView(path).tree_text())
            for item in items:
                key = item.spec.collection_index
                test = state.tests.get(key)
                execution = state.executions.get(key)
                branch = tree.add(self._build_live_item_line(item, execution))
                if execution is not None and execution.sub_executions:
                    self._add_live_sub_executions(
                        branch, execution.sub_executions, state
                    )
                elif (
                    execution is None
                    and isinstance(test, CompositeTest)
                ):
                    self._add_live_composite_children(branch, test, state)
                elif execution is None:
                    early = self._early_sub_executions(item, state)
                    if early:
                        self._add_live_sub_executions(branch, early, state)
            trees.append(tree)
        return Group(*trees) if trees else Text("")

    def _early_sub_executions(
        self, item: LoadedTestDef, state: ConsoleReporter
    ) -> list[ExecutedTest]:
        """Sub-executions that completed before the parent finished."""
        return [
            ex
            for ex in state.all_executions.values()
            if (
                ex.definition.spec.collection_index
                == item.spec.collection_index
                and not state.is_top_level_definition(ex.definition)
            )
        ]

    def print_completed_module(
        self,
        path: Path | None,
        items: list[LoadedTestDef],
        state: ConsoleReporter,
    ) -> None:
        tree = Tree(ConsoleModuleView(path).tree_text())
        for item in items:
            execution = state.executions.get(item.spec.collection_index)
            branch = tree.add(self._build_live_item_line(item, execution))
            if execution is not None and execution.sub_executions:
                self._add_live_sub_executions(
                    branch, execution.sub_executions, state
                )
        self.console.print(tree)
        state.current_module = path

    def print_test(
        self, execution: ExecutedTest, state: ConsoleReporter
    ) -> None:
        definition = execution.definition
        if state.current_module != definition.spec.locator.module_path:
            if state.current_module is not None:
                self.console.print(Text(""))
            self.console.print(
                ConsoleModuleView(
                    definition.spec.locator.module_path
                ).tree_text()
            )
            state.current_module = definition.spec.locator.module_path

        view = ConsoleExecutionView.from_execution(
            execution, verbosity=state.verbosity
        )
        if execution.sub_executions:
            self.console.print(
                view.render_test_line(name=definition.spec.local_name)
            )
            for renderable in self._iter_sub_executions(
                execution.sub_executions,
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
                ConsoleExecutionView.running_line(item.spec.local_name)
            )
        view = ConsoleExecutionView.from_execution(execution)
        return view.render_live_item_line(name=item.spec.local_name)

    def _add_live_composite_children(
        self, parent: Tree, test: CompositeTest, state: ConsoleReporter
    ) -> None:
        for child in test.children:
            child_exec = state.all_executions.get(id(child.definition))
            if child_exec is not None:
                parent.add(
                    self._render_sub_live_line(
                        child_exec,
                        verbosity=state.verbosity,
                    )
                )
                if child_exec.sub_executions:
                    self._add_live_sub_executions(
                        parent.children[-1],
                        child_exec.sub_executions,
                        state,
                    )
            elif isinstance(child, CompositeTest):
                pending_label = (
                    child.definition.spec.get_label(
                        full=state.verbosity >= 2
                    )
                )
                pending = ConsoleExecutionView.sub_label_text(
                    pending_label or "case"
                )
                pending.append("  ⋯", style="dim")
                node = parent.add(pending)
                self._add_live_composite_children(node, child, state)

    def _add_live_sub_executions(
        self,
        parent: Tree,
        sub_executions: list[ExecutedTest],
        state: ConsoleReporter,
    ) -> None:
        for sub in sub_executions:
            node = parent
            if sub.result.status in {
                TestStatus.PASSED,
                TestStatus.FAILED,
                TestStatus.ERROR,
            }:
                node = parent.add(
                    self._render_sub_live_line(
                        sub, verbosity=state.verbosity
                    )
                )
            if sub.sub_executions:
                self._add_live_sub_executions(node, sub.sub_executions, state)

    def _render_sub_live_line(
        self, execution: ExecutedTest, *, verbosity: int
    ) -> Text:
        view = ConsoleExecutionView.from_execution(
            execution, verbosity=verbosity
        )
        return view.render_sub_live_line()


def make_mode(verbosity: int, console: Console) -> OutputMode:
    if verbosity < 0:
        return QuietMode(console)
    if verbosity == 0:
        return CompactMode(console)
    return VerboseMode(console)
