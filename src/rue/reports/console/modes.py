"""Output mode strategy: QuietMode, CompactMode, VerboseMode."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.markup import escape
from rich.text import Text
from rich.tree import Tree

from rue.testing.execution.composite import CompositeTest
from rue.testing.models import TestStatus

from .shared import (
    STATUS_STYLES,
    format_label,
    get_execution_label,
    get_modifier_suffix,
    get_status_extra,
    iter_sub_executions,
    render_spinner_line,
    render_test_line,
    safe_relative_path,
)

if TYPE_CHECKING:
    from pathlib import Path

    from rue.testing.models.definition import TestDefinition
    from rue.testing.models.result import TestExecution

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

    @abstractmethod
    def render_live(self, state: ConsoleReporter) -> RenderableType: ...

    @abstractmethod
    def print_test(self, execution: TestExecution, state: ConsoleReporter) -> None: ...

    def print_completed_module(
        self,
        path: Path,
        items: list[TestDefinition],
        state: ConsoleReporter,
    ) -> None:
        for item in items:
            execution = state.executions.get(id(item))
            if execution is not None:
                self.print_test(execution, state)


class QuietMode(OutputMode):
    @property
    def show_collected_count(self) -> bool:
        return False

    def render_live(self, state: ConsoleReporter) -> RenderableType:
        text = Text.from_markup(
            f"Running tests... {state.completed_count}/{state.total_tests} completed"
        )
        return render_spinner_line(text)

    def print_test(self, execution: TestExecution, state: ConsoleReporter) -> None:
        pass


class CompactMode(OutputMode):
    def render_live(self, state: ConsoleReporter) -> RenderableType:
        lines: list[RenderableType] = []
        for path, items in state.items_by_file.items():
            if path in state.completed_modules:
                continue
            rel = safe_relative_path(path)
            line = Text(f" • {rel.as_posix()} ")
            has_running = False
            for item in items:
                execution = state.executions.get(id(item))
                if execution is None:
                    has_running = True
                    line.append("⋯", style="dim")
                    continue
                style = STATUS_STYLES[execution.result.status]
                line.append(style.symbol, style=style.color)
            lines.append(render_spinner_line(line) if has_running else line)
        return Group(*lines) if lines else Text("")

    def print_test(self, execution: TestExecution, state: ConsoleReporter) -> None:
        item = execution.item
        style = STATUS_STYLES[execution.result.status]
        if state.current_module != item.module_path:
            if state.current_module is not None:
                self.console.print()
            rel = safe_relative_path(item.module_path)
            self.console.print(f" • {rel.as_posix()} ", end="")
            state.current_module = item.module_path
        self.console.print(Text(style.symbol, style=style.color), end="")

    def print_completed_module(
        self,
        path: Path,
        items: list[TestDefinition],
        state: ConsoleReporter,
    ) -> None:
        rel = safe_relative_path(path)
        line = Text(f" • {rel.as_posix()} ")
        for item in items:
            execution = state.executions.get(id(item))
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

    def render_live(self, state: ConsoleReporter) -> RenderableType:
        trees: list[Tree] = []
        for path, items in state.items_by_file.items():
            if path in state.completed_modules:
                continue
            rel = safe_relative_path(path)
            tree = Tree(f"• {rel.as_posix()}")
            for item in items:
                test = state.tests.get(id(item))
                execution = state.executions.get(id(item))
                branch = tree.add(self._build_live_item_line(item, execution))
                if execution is not None and execution.sub_executions:
                    self._add_live_sub_executions(branch, execution.sub_executions, state)
                elif isinstance(test, CompositeTest) and execution is None:
                    self._add_live_composite_children(branch, test, state)
                elif execution is None:
                    early = self._early_sub_executions(item, state)
                    if early:
                        self._add_live_sub_executions(branch, early, state)
            trees.append(tree)
        return Group(*trees) if trees else Text("")

    def _early_sub_executions(
        self, item: TestDefinition, state: ConsoleReporter
    ) -> list[TestExecution]:
        """Sub-executions that completed before the parent finished."""
        return [
            ex
            for item_id, ex in state.executions.items()
            if item_id not in state.item_ids
            and ex.definition.name == item.name
            and ex.definition.module_path == item.module_path
        ]

    def print_completed_module(
        self,
        path: Path,
        items: list[TestDefinition],
        state: ConsoleReporter,
    ) -> None:
        rel = safe_relative_path(path)
        tree = Tree(f"• {rel.as_posix()}")
        for item in items:
            execution = state.executions.get(id(item))
            branch = tree.add(self._build_live_item_line(item, execution))
            if execution is not None and execution.sub_executions:
                self._add_live_sub_executions(branch, execution.sub_executions, state)
        self.console.print(tree)
        state.current_module = path

    def print_test(self, execution: TestExecution, state: ConsoleReporter) -> None:
        item = execution.item
        if state.current_module != item.module_path:
            rel = safe_relative_path(item.module_path)
            if state.current_module is not None:
                self.console.print(Text(""))
            self.console.print(Text(f"• {rel.as_posix()}"))
            state.current_module = item.module_path

        if execution.sub_executions:
            modifier_suffix = get_modifier_suffix(execution)
            self.console.print(
                render_test_line(f"{item.full_name}{modifier_suffix}", execution.result)
            )
            for renderable in iter_sub_executions(execution.sub_executions, indent=4):
                self.console.print(renderable)
        else:
            extra = get_status_extra(execution.result)
            self.console.print(
                render_test_line(item.full_name, execution.result, extra=extra)
            )

    def _build_live_item_line(
        self,
        item: TestDefinition,
        execution: TestExecution | None,
    ) -> RenderableType:
        if execution is None:
            text = Text.from_markup(f"{item.full_name} [dim]⋯ running[/dim]")
            return render_spinner_line(text)
        result = execution.result
        style = STATUS_STYLES[result.status]
        extra = get_status_extra(result)
        modifier_suffix = get_modifier_suffix(execution)
        text = Text()
        text.append(f"{item.full_name}{modifier_suffix} ")
        text.append(f"({result.duration_ms:.1f}ms) ", style="dim")
        if extra:
            text.append(f"{extra} ", style="dim")
        text.append(style.label, style=style.color)
        return text

    def _add_live_composite_children(
        self, parent: Tree, test: CompositeTest, state: ConsoleReporter
    ) -> None:
        for child in test.children:
            child_exec = state.executions.get(id(child.definition))
            if child_exec is not None:
                style = STATUS_STYLES[child_exec.result.status]
                sub_label = format_label(get_execution_label(child_exec))
                modifier_suffix = get_modifier_suffix(child_exec)
                text = Text()
                text.append(f"{sub_label}{modifier_suffix} ")
                text.append(f"({child_exec.result.duration_ms:.1f}ms) ", style="dim")
                text.append(style.label, style=style.color)
                node = parent.add(text)
                if child_exec.sub_executions:
                    self._add_live_sub_executions(node, child_exec.sub_executions, state)
            elif isinstance(child, CompositeTest):
                node = parent.add(
                    Text.from_markup(
                        f"{escape(format_label(child.definition.suffix or 'case'))} [dim]⋯[/dim]"
                    )
                )
                self._add_live_composite_children(node, child, state)

    def _add_live_sub_executions(
        self,
        parent: Tree,
        sub_executions: list[TestExecution],
        state: ConsoleReporter,
    ) -> None:
        for sub in sub_executions:
            node = parent
            if sub.result.status in {
                TestStatus.PASSED,
                TestStatus.FAILED,
                TestStatus.ERROR,
            }:
                style = STATUS_STYLES[sub.result.status]
                sub_label = format_label(get_execution_label(sub))
                modifier_suffix = get_modifier_suffix(sub)
                text = Text()
                text.append(f"{sub_label}{modifier_suffix} ")
                text.append(f"({sub.result.duration_ms:.1f}ms) ", style="dim")
                text.append(style.label, style=style.color)
                node = parent.add(text)
            if sub.sub_executions:
                self._add_live_sub_executions(node, sub.sub_executions, state)


def make_mode(verbosity: int, console: Console) -> OutputMode:
    if verbosity < 0:
        return QuietMode(console)
    if verbosity == 0:
        return CompactMode(console)
    return VerboseMode(console)
