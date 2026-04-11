"""Shared primitives: status styles and pure formatting utilities."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text

from rue.testing.models import TestStatus

if TYPE_CHECKING:
    from rue.assertions import AssertionRepr, AssertionResult


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
