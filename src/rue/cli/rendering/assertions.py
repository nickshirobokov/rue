"""Assertion output rendering."""

# ruff: noqa: D101,D102

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text

from rue.cli.rendering.primitives import (
    dedented_source_block,
    oneline,
    truncate,
)


if TYPE_CHECKING:
    from rue.assertions import AssertionRepr, AssertionResult


_METRIC_PREFIX_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class AssertionView:
    expression_repr: AssertionRepr
    passed: bool
    error_message: str | None

    @classmethod
    def from_result(
        cls,
        assertion: AssertionResult,
    ) -> AssertionView:
        return cls(
            expression_repr=assertion.expression_repr,
            passed=assertion.passed,
            error_message=assertion.error_message,
        )

    def render(self, heading: str) -> Text:
        expr = self.expression_repr
        text = Text()
        color = "green" if self.passed else "red"

        text.append("✓ " if self.passed else "✗ ", style=f"bold {color}")
        text.append(heading, style="bold")
        if self.error_message:
            text.append("  ")
            text.append(self.error_message, style="italic")

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

    def snippet(self, *, strip_metric_prefix: bool = False) -> Text:
        expr = oneline(self.expression_repr.expr)
        if expr.startswith("assert "):
            expr = expr[7:]
        if strip_metric_prefix:
            expr = self._strip_metric_prefix(expr)

        style = "red" if not self.passed else "green"
        resolved: list[tuple[str, str]] = []
        for label, value in self.expression_repr.resolved_args.items():
            normalized = oneline(label)
            if strip_metric_prefix:
                normalized = self._strip_metric_prefix(normalized)
            if normalized:
                resolved.append((normalized, oneline(value)))
        resolved.sort(key=lambda item: len(item[0]), reverse=True)

        snippet = Text()
        i = 0
        while i < len(expr):
            match next(
                (
                    (label, value)
                    for label, value in resolved
                    if expr.startswith(label, i)
                ),
                None,
            ):
                case (label, value):
                    snippet.append(label, style="grey62")
                    snippet.append(" / ", style="dim")
                    snippet.append(value)
                    i += len(label)
                case None:
                    snippet.append(expr[i], style=style)
                    i += 1

        return snippet

    @staticmethod
    def _strip_metric_prefix(expr: str) -> str:
        if "." not in expr:
            return expr
        prefix, rest = expr.split(".", 1)
        if _METRIC_PREFIX_RE.fullmatch(prefix):
            return rest
        return expr



__all__ = ["AssertionView"]
