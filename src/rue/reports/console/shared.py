"""Shared primitives: status styles and pure formatting utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import RenderableType
from rich.markup import escape
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from rue.testing.models import TestStatus

if TYPE_CHECKING:
    from rue.testing.models.definition import TestDefinition
    from rue.testing.models.result import TestExecution, TestResult


@dataclass(frozen=True, slots=True)
class StatusStyle:
    symbol: str
    color: str
    label: str


STATUS_STYLES: dict[TestStatus, StatusStyle] = {
    TestStatus.PASSED: StatusStyle("✓", "green", "PASSED"),
    TestStatus.FAILED: StatusStyle("✗", "red", "FAILED"),
    TestStatus.ERROR: StatusStyle("!", "yellow", "ERROR"),
    TestStatus.SKIPPED: StatusStyle("-", "yellow", "SKIPPED"),
    TestStatus.XFAILED: StatusStyle("x", "blue", "XFAILED"),
    TestStatus.XPASSED: StatusStyle("!", "magenta", "XPASSED"),
}


def safe_relative_path(path: Path) -> Path:
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def format_label(label: str) -> str:
    return escape(f"[{label}]")


def get_definition_label(item: TestDefinition) -> str | None:
    if item.suffix:
        return item.suffix
    if item.case_id:
        return str(item.case_id)
    return None


def get_execution_label(execution: TestExecution) -> str:
    label = get_definition_label(execution.definition)
    if label:
        return label
    if execution.execution_id:
        return str(execution.execution_id)[:8]
    return "case"


def get_modifier_suffix(execution: TestExecution) -> str:
    if execution.definition.modifiers and execution.sub_executions:
        return format_label(execution.definition.modifiers[0].display_name)
    return ""


def get_status_extra(result: TestResult) -> str:
    if result.status == TestStatus.SKIPPED:
        reason = result.error.args[0] if result.error else "skipped"
        return f"skipped ({reason})"
    if result.status == TestStatus.XFAILED:
        reason = result.error.args[0] if result.error else "expected failure"
        return f"xfailed ({reason})"
    if result.status == TestStatus.XPASSED:
        return "XPASS"
    return ""


def render_spinner_line(text: Text) -> Table:
    line = Table.grid(padding=(0, 1))
    line.add_column()
    line.add_column(no_wrap=True)
    line.add_row(text, Spinner("simpleDots", style="bold blue"))
    return line


def render_test_line(
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


def render_sub_execution_line(sub: TestExecution, indent: int) -> Text:
    style = STATUS_STYLES[sub.result.status]
    sub_label = format_label(get_execution_label(sub))
    modifier_suffix = get_modifier_suffix(sub)
    text = Text(" " * indent + "• ")
    text.append(f"{sub_label}{modifier_suffix}")
    text.append(f" ({sub.result.duration_ms:.1f}ms)", style="dim")
    text.append(f" {style.label}", style=style.color)
    return text


def iter_sub_executions(
    sub_executions: list[TestExecution], indent: int
) -> list[RenderableType]:
    renderables: list[RenderableType] = []
    for sub in sub_executions:
        if sub.result.status in {
            TestStatus.PASSED,
            TestStatus.FAILED,
            TestStatus.ERROR,
        }:
            renderables.append(render_sub_execution_line(sub, indent))
        if sub.sub_executions:
            renderables.extend(iter_sub_executions(sub.sub_executions, indent + 2))
    return renderables
