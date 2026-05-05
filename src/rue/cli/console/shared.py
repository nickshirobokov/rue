"""Shared primitives: status styles and pure formatting utilities."""

# ruff: noqa: D101,D103

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rue.testing.models import TestStatus


if TYPE_CHECKING:
    from rue.assertions import AssertionRepr


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
