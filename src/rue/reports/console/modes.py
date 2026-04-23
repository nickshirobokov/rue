"""Output mode strategy: QuietMode, CompactMode, VerboseMode."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rich.console import Console, Group, RenderableType
from rich.markup import escape
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from rue.testing.execution.composite import CompositeTest
from rue.testing.models import (
    BackendModifier,
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    ParamsIterateModifier,
    TestStatus,
)

from .shared import STATUS_STYLES, safe_relative_path

if TYPE_CHECKING:
    from pathlib import Path

    from rue.testing.models.loaded import LoadedTestDef
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.result import TestResult

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
        path: Path,
        items: list[LoadedTestDef],
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
            rel = safe_relative_path(path)
            line = Text(f" • {rel.as_posix()} ")
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
        if state.current_module != definition.spec.module_path:
            if state.current_module is not None:
                self.console.print()
            rel = safe_relative_path(definition.spec.module_path)
            self.console.print(f" • {rel.as_posix()} ", end="")
            state.current_module = definition.spec.module_path
        self.console.print(Text(style.symbol, style=style.color), end="")

    def print_completed_module(
        self,
        path: Path,
        items: list[LoadedTestDef],
        state: ConsoleReporter,
    ) -> None:
        rel = safe_relative_path(path)
        line = Text(f" • {rel.as_posix()} ")
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

    def _get_modifier_suffix(self, execution: ExecutedTest) -> str:
        if not execution.definition.spec.modifiers or not execution.sub_executions:
            return ""
        mod = execution.definition.spec.modifiers[0]
        match mod:
            case IterateModifier(count=n, display_name=name):
                return f" x {n} {name}"
            case CasesIterateModifier(cases=cases, display_name=name):
                return f" x {len(cases)} {name}"
            case GroupsIterateModifier(groups=groups, display_name=name):
                return f" x {len(groups)} {name}"
            case ParamsIterateModifier(parameter_sets=pss, display_name=name):
                return f" x {len(pss)} {name}"
            case BackendModifier():
                return ""
            case _:
                return ""

    def _render_test_line(
        self,
        name: str,
        result: TestResult,
        *,
        extra: str = "",
        indent: int = 2,
    ) -> Text:
        style = STATUS_STYLES[result.status]
        text = Text(" " * indent + "• ")
        text.append(name)
        text.append(f" ({result.duration_ms:.1f}ms)", style="dim")
        if extra:
            text.append(f" {extra}", style="dim")
        text.append(f" {style.label}", style=style.color)
        return text

    def _iter_sub_executions(
        self, sub_executions: list[ExecutedTest], indent: int
    ) -> list[RenderableType]:
        renderables: list[RenderableType] = []
        for sub in sub_executions:
            if sub.result.status in {
                TestStatus.PASSED,
                TestStatus.FAILED,
                TestStatus.ERROR,
            }:
                style = STATUS_STYLES[sub.result.status]
                sub_label = f"[{sub.label}]"
                modifier_suffix = self._get_modifier_suffix(sub)
                line = Text(" " * indent + "• ")
                line.append(f"{sub_label}{modifier_suffix}")
                line.append(f" ({sub.result.duration_ms:.1f}ms)", style="dim")
                line.append(f" {style.label}", style=style.color)
                renderables.append(line)
            if sub.sub_executions:
                renderables.extend(
                    self._iter_sub_executions(sub.sub_executions, indent + 2)
                )
        return renderables

    def render_live(self, state: ConsoleReporter) -> RenderableType:
        trees: list[Tree] = []
        for path, items in state.items_by_file.items():
            if path in state.completed_modules:
                continue
            rel = safe_relative_path(path)
            tree = Tree(f"• {rel.as_posix()}")
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
        path: Path,
        items: list[LoadedTestDef],
        state: ConsoleReporter,
    ) -> None:
        rel = safe_relative_path(path)
        tree = Tree(f"• {rel.as_posix()}")
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
        if state.current_module != definition.spec.module_path:
            rel = safe_relative_path(definition.spec.module_path)
            if state.current_module is not None:
                self.console.print(Text(""))
            self.console.print(Text(f"• {rel.as_posix()}"))
            state.current_module = definition.spec.module_path

        if execution.sub_executions:
            modifier_suffix = self._get_modifier_suffix(execution)
            self.console.print(
                self._render_test_line(
                    f"{definition.spec.full_name}{modifier_suffix}",
                    execution.result,
                )
            )
            for renderable in self._iter_sub_executions(
                execution.sub_executions, indent=4
            ):
                self.console.print(renderable)
        else:
            extra = execution.result.status_repr
            self.console.print(
                self._render_test_line(
                    definition.spec.full_name, execution.result, extra=extra
                )
            )

    def _build_live_item_line(
        self,
        item: LoadedTestDef,
        execution: ExecutedTest | None,
    ) -> RenderableType:
        if execution is None:
            text = Text.from_markup(
                f"{item.spec.full_name} [dim]⋯ running[/dim]"
            )
            return self._render_spinner_line(text)
        result = execution.result
        style = STATUS_STYLES[result.status]
        extra = result.status_repr
        modifier_suffix = self._get_modifier_suffix(execution)
        text = Text()
        text.append(f"{item.spec.full_name}{modifier_suffix} ")
        text.append(f"({result.duration_ms:.1f}ms) ", style="dim")
        if extra:
            text.append(f"{extra} ", style="dim")
        text.append(style.label, style=style.color)
        return text

    def _add_live_composite_children(
        self, parent: Tree, test: CompositeTest, state: ConsoleReporter
    ) -> None:
        for child in test.children:
            child_exec = state.all_executions.get(id(child.definition))
            if child_exec is not None:
                style = STATUS_STYLES[child_exec.result.status]
                sub_label = f"[{child_exec.label}]"
                modifier_suffix = self._get_modifier_suffix(child_exec)
                text = Text()
                text.append(f"{sub_label}{modifier_suffix} ")
                text.append(
                    f"({child_exec.result.duration_ms:.1f}ms) ", style="dim"
                )
                text.append(style.label, style=style.color)
                node = parent.add(text)
                if child_exec.sub_executions:
                    self._add_live_sub_executions(
                        node, child_exec.sub_executions, state
                    )
            elif isinstance(child, CompositeTest):
                pending = f"[{child.definition.spec.suffix or 'case'}]"
                node = parent.add(
                    Text.from_markup(f"{escape(pending)} [dim]⋯[/dim]")
                )
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
                style = STATUS_STYLES[sub.result.status]
                sub_label = f"[{sub.label}]"
                modifier_suffix = self._get_modifier_suffix(sub)
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
