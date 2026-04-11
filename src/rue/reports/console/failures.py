"""Renders exception/traceback panels for errored test executions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.traceback import Traceback

from .shared import STATUS_STYLES

if TYPE_CHECKING:
    from rue.testing.models.result import TestExecution

_RUE_MODULE = __import__("rue")


class ExceptionRenderer:
    def __init__(self, show_locals: bool = False) -> None:
        self.show_locals = show_locals

    @staticmethod
    def _should_show_error(execution: TestExecution) -> bool:
        result = execution.result
        if result.error is None:
            return False
        failed = [a for a in result.assertion_results if not a.passed]
        return not (isinstance(result.error, AssertionError) and failed)

    @classmethod
    def _has_exception(cls, execution: TestExecution) -> bool:
        if cls._should_show_error(execution):
            return True
        return any(cls._has_exception(s) for s in execution.sub_executions)

    def render(self, failures: list[TestExecution]) -> list[RenderableType]:
        relevant = [f for f in failures if self._has_exception(f)]
        if not relevant:
            return []
        renderables: list[RenderableType] = [Text(""), Rule("ERRORS", characters="=")]
        for index, failure in enumerate(relevant):
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
        renderables: list[RenderableType] = []

        if self._should_show_error(execution):
            err = result.error
            assert err is not None
            if err.__traceback__:
                renderables.append(
                    Traceback.from_exception(
                        type(err),
                        err,
                        err.__traceback__,
                        suppress=[_RUE_MODULE],
                        show_locals=self.show_locals,
                    )
                )
            else:
                renderables.append(escape(f"{type(err).__name__}: {err}"))

        renderables.extend(
            self.render_panel(sub)
            for sub in execution.sub_executions
            if self._has_exception(sub)
        )

        match renderables:
            case []:
                panel_content = " "
            case [single]:
                panel_content = single
            case _:
                panel_content = Group(*renderables)

        return Panel(
            panel_content,
            title=title or execution.label,
            title_align="left",
            border_style=style.color,
            expand=True,
            padding=(1, 1),
        )
