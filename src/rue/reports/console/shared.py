"""Shared primitives: status styles and pure formatting utilities."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from rue.testing.models import TestStatus

if TYPE_CHECKING:
    from rue.assertions import AssertionRepr, AssertionResult
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

_WS_BEFORE_CLOSE = re.compile(r"\s+([)\]}.,])")
_WS_AFTER_OPEN = re.compile(r"([(\[{])\s+")
_DOT_SPACES = re.compile(r"\s*\.\s*")


def safe_relative_path(path: Path) -> Path:
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def dedented_source_block(
    expr: AssertionRepr,
) -> tuple[list[str], list[str], list[str]]:
    block: list[str] = []

    raw_above = expr.lines_above.strip("\n")
    above_lines = raw_above.splitlines() if raw_above else []
    block.extend(above_lines)
    n_above = len(above_lines)

    indented = " " * expr.col_offset + expr.expr
    expr_split = indented.splitlines()
    block.extend(expr_split)
    n_expr = len(expr_split)

    raw_below = expr.lines_below.strip("\n")
    below_lines = raw_below.splitlines() if raw_below else []
    block.extend(below_lines)

    if not block:
        return [], [], []

    dedented = textwrap.dedent("\n".join(block)).splitlines()
    return (
        dedented[:n_above],
        dedented[n_above : n_above + n_expr],
        dedented[n_above + n_expr :],
    )


def oneline(s: str) -> str:
    s = " ".join(s.split())
    s = _WS_BEFORE_CLOSE.sub(r"\1", s)
    s = _WS_AFTER_OPEN.sub(r"\1", s)
    return _DOT_SPACES.sub(".", s)


def truncate(s: str, max_len: int = 120) -> str:
    return s if len(s) <= max_len else s[:max_len] + "…"


def format_assertion_result(
    assertion: AssertionResult,
    *,
    heading: str,
) -> Text:
    expr = assertion.expression_repr
    text = Text()
    color = "green" if assertion.passed else "red"

    text.append("✓ " if assertion.passed else "✗ ", style=f"bold {color}")
    text.append(heading, style="bold")
    if assertion.error_message:
        text.append("  ")
        text.append(assertion.error_message, style="italic")

    above, expr_lines, below = dedented_source_block(expr)

    for line in above:
        text.append("\n")
        text.append(f"│  {line}", style="dim")
    for line in expr_lines:
        text.append("\n")
        text.append(">  ", style=f"bold {color}")
        text.append(line, style="bold")
    for line in below:
        text.append("\n")
        text.append(f"│  {line}", style="dim")

    if expr.resolved_args:
        text.append("\n")
        text.append("│", style="dim")
        text.append("\n")
        text.append("╰─ where:", style="dim italic")
        for name, value in expr.resolved_args.items():
            text.append("\n     ")
            text.append(oneline(name), style="bold")
            text.append(" = ", style="dim")
            text.append(truncate(oneline(value)), style="cyan")

    return text


def format_label(label: str) -> str:
    return f"[{label}]"


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


_STAT_ORDER = [
    (TestStatus.PASSED, "passed"),
    (TestStatus.FAILED, "failed"),
    (TestStatus.ERROR, "errors"),
    (TestStatus.SKIPPED, "skipped"),
    (TestStatus.XFAILED, "xfailed"),
    (TestStatus.XPASSED, "xpassed"),
]


def render_progress_bar(
    completed: int, total: int, status_counts: dict[TestStatus, int]
) -> Panel:
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
    for status, label in _STAT_ORDER:
        count = status_counts.get(status, 0)
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
