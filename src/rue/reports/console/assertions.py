"""Renders assertion failure panels for failed test executions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from .shared import STATUS_STYLES, format_assertion_result


if TYPE_CHECKING:
    from rue.testing.models.executed import ExecutedTest


class AssertionRenderer:
    @staticmethod
    def _has_failed_assertions(execution: ExecutedTest) -> bool:
        if any(not a.passed for a in execution.result.assertion_results):
            return True
        return any(
            AssertionRenderer._has_failed_assertions(s)
            for s in execution.sub_executions
        )

    def render(
        self, failures: list[ExecutedTest], verbosity: int
    ) -> list[RenderableType]:
        relevant = [f for f in failures if self._has_failed_assertions(f)]
        if not relevant:
            return []
        renderables: list[RenderableType] = [
            Text(""),
            Rule(
                Text("ASSERTIONS", style="bold red"),
                characters="=",
                style="red",
            ),
        ]
        for index, failure in enumerate(relevant):
            if index:
                renderables.append(Text(""))
            renderables.append(
                self.render_panel(
                    failure,
                    title=failure.definition.spec.full_name,
                    verbosity=verbosity,
                )
            )
        renderables.append(Text(""))
        return renderables

    def render_panel(
        self,
        execution: ExecutedTest,
        *,
        title: str | None = None,
        verbosity: int,
    ) -> Panel:
        result = execution.result
        style = STATUS_STYLES[result.status]
        renderables: list[RenderableType] = []

        failed = [a for a in result.assertion_results if not a.passed]
        if failed:
            combined = Text()
            for i, assertion in enumerate(failed):
                if i:
                    combined.append("\n\n")
                combined.append_text(
                    format_assertion_result(
                        assertion,
                        heading="Failed Assertion",
                    )
                )
            renderables.append(combined)

        renderables.extend(
            self.render_panel(sub, verbosity=verbosity)
            for sub in execution.sub_executions
            if self._has_failed_assertions(sub)
        )

        match renderables:
            case []:
                panel_content = " "
            case [single]:
                panel_content = single
            case _:
                panel_content = Group(*renderables)

        fallback_title = execution.definition.spec.get_label(
            full=verbosity >= 2
        )
        return Panel(
            panel_content,
            title=Text(
                title or fallback_title or execution.label,
                style=f"bold {style.color}",
            ),
            title_align="left",
            border_style=style.color,
            expand=True,
            padding=(1, 1),
        )
