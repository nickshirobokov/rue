"""Renders failure panels for failed/errored test executions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.traceback import Traceback

from .shared import STATUS_STYLES, get_definition_label, get_execution_label

if TYPE_CHECKING:
    from rue.assertions.base import AssertionResult
    from rue.testing.models.result import TestExecution, TestResult


class FailureRenderer:
    def __init__(self, show_locals: bool = False) -> None:
        self.show_locals = show_locals

    def render(self, failures: list[TestExecution]) -> list[RenderableType]:
        renderables: list[RenderableType] = [Text(""), Rule("FAILURES", characters="=")]
        for index, failure in enumerate(failures):
            if index:
                renderables.append(Text(""))
            renderables.append(self.render_panel(failure, title=failure.item.full_name))
        renderables.append(Text(""))
        return renderables

    def render_panel(
        self, execution: TestExecution, *, title: str | None = None
    ) -> Panel:
        result = execution.result
        style = STATUS_STYLES[result.status]
        sub_failures = [
            sub for sub in execution.sub_executions if sub.result.status.is_failure
        ]
        renderables: list[RenderableType] = []

        content = self._format_result_content(result)
        if isinstance(content, Traceback):
            renderables.append(content)
        elif content:
            renderables.append("\n".join(escape(line) for line in content))

        renderables.extend(self.render_panel(sub) for sub in sub_failures)

        panel_content: RenderableType = (
            " "
            if not renderables
            else renderables[0]
            if len(renderables) == 1
            else Group(*renderables)
        )
        panel_title = title or self._panel_title(execution)
        return Panel(
            panel_content,
            title=panel_title,
            title_align="left",
            border_style=style.color,
            expand=True,
            padding=(1, 1),
        )

    def _panel_title(self, execution: TestExecution) -> str:
        label = get_definition_label(execution.definition)
        if label:
            return label
        if execution.execution_id:
            return str(execution.execution_id)[:8]
        return "case"

    def _format_result_content(
        self, result: TestResult
    ) -> list[str] | Traceback:
        lines = self._format_assertions(result.assertion_results)
        return lines if lines else self._format_error(result.error)

    def _format_assertions(
        self, assertion_results: list[AssertionResult]
    ) -> list[str]:
        lines: list[str] = []
        for assertion in (a for a in assertion_results if not a.passed):
            if lines:
                lines.append("")
            expr = assertion.expression_repr
            lines.append(f"> {expr.expr}")
            lines.append(
                assertion.error_message or f"Assertion failed: {expr.expr}"
            )
            if expr.resolved_args:
                lines.append(f"{expr.resolved_args}")
        return lines

    def _format_error(
        self, error: BaseException | None
    ) -> list[str] | Traceback:
        if not error:
            return []
        if error.__traceback__:
            return Traceback.from_exception(
                type(error),
                error,
                error.__traceback__,
                suppress=[__import__("rue")],
                show_locals=self.show_locals,
            )
        return [f"{type(error).__name__}: {error}"]
