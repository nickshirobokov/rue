"""Run output view models."""

# ruff: noqa: D102

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.traceback import Traceback

from rue.cli.rendering.assertions import AssertionView
from rue.cli.rendering.primitives import (
    STATUS_STYLES,
    StatusStyle,
)
from rue.testing.models import TestStatus


if TYPE_CHECKING:
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import ExecutedRun


_MODIFIER_STYLE = "cyan"
_RUE_MODULE = __import__("rue")


@dataclass(frozen=True, slots=True)
class RunView:
    """Render-ready summary of an ExecutedRun header and final counts."""

    run_id: str
    platform: str
    python_version: str
    rue_version: str
    working_directory: str
    branch: str | None
    commit_hash: str | None
    dirty: bool | None
    passed: int
    failed: int
    errors: int
    skipped: int
    xfailed: int
    xpassed: int
    total_duration_ms: float

    @classmethod
    def from_run(cls, run: ExecutedRun) -> RunView:
        """Project a domain run object into terminal display fields."""
        environment = run.environment
        return cls(
            run_id=str(run.run_id),
            platform=environment.platform,
            python_version=environment.python_version,
            rue_version=environment.rue_version,
            working_directory=environment.working_directory,
            branch=environment.branch,
            commit_hash=environment.commit_hash,
            dirty=environment.dirty,
            passed=run.result.passed,
            failed=run.result.failed,
            errors=run.result.errors,
            skipped=run.result.skipped,
            xfailed=run.result.xfailed,
            xpassed=run.result.xpassed,
            total_duration_ms=run.result.total_duration_ms,
        )

    @property
    def short_commit(self) -> str | None:
        if self.commit_hash is None:
            return None
        return self.commit_hash[:8]

    @property
    def git_summary(self) -> str | None:
        if self.branch is None or self.short_commit is None:
            return None
        dirty = " dirty" if self.dirty else ""
        return f"{self.branch} ({self.short_commit}){dirty}"

    @property
    def summary_markup(self) -> str:
        parts = []
        if self.passed:
            parts.append(f"[bold green]{self.passed} passed[/bold green]")
        if self.failed:
            parts.append(f"[bold red]{self.failed} failed[/bold red]")
        if self.errors:
            parts.append(f"[bold yellow]{self.errors} errors[/bold yellow]")
        if self.skipped:
            parts.append(f"[yellow]{self.skipped} skipped[/yellow]")
        if self.xfailed:
            parts.append(f"[blue]{self.xfailed} xfailed[/blue]")
        if self.xpassed:
            parts.append(f"[magenta]{self.xpassed} xpassed[/magenta]")
        return ", ".join(parts) if parts else "[dim]0 tests[/dim]"

    @property
    def duration_markup(self) -> str:
        return (
            f"{self.summary_markup} "
            f"[dim]in {self.total_duration_ms:.0f}ms[/dim]"
        )

    @property
    def run_id_markup(self) -> str:
        return f"[dim]run_id: {self.run_id}[/dim]"

    def render_header(self) -> Group:
        """Render the banner printed before a run starts executing tests."""
        platform_text = Text()
        platform_text.append("platform ", style="dim")
        platform_text.append(self.platform)
        platform_text.append("  python ", style="dim")
        platform_text.append(self.python_version)
        platform_text.append("  rue ", style="dim")
        platform_text.append(self.rue_version)

        rootdir_text = Text()
        rootdir_text.append("rootdir: ", style="dim")
        rootdir_text.append(self.working_directory)

        parts: list[RenderableType] = [
            Rule(Text("RUE RUN STARTS", style="bold cyan"), characters="="),
            platform_text,
            rootdir_text,
        ]
        if self.run_id:
            run_id_text = Text()
            run_id_text.append("run_id: ", style="dim")
            run_id_text.append(self.run_id, style="dim")
            parts.append(run_id_text)
        if self.git_summary is not None:
            git_text = Text()
            git_text.append("git: ", style="dim")
            git_text.append(self.git_summary)
            parts.append(git_text)
        return Group(*parts)

    def render_summary(self) -> Group:
        """Render the final run count and run id block."""
        return Group(
            Rule(Text("SUMMARY", style="bold cyan"), characters="="),
            Text.from_markup(self.duration_markup, justify="center"),
            Text.from_markup(self.run_id_markup, justify="center"),
            Rule(characters="="),
        )


@dataclass(frozen=True, slots=True)
class ExecutionView:
    """Render-ready view of one executed test node and its children."""

    label: str
    local_name: str
    title: str
    status: TestStatus
    status_style: StatusStyle
    duration_ms: float
    status_repr: str
    modifier_suffix: str
    error: BaseException | None
    failed_assertions: tuple[AssertionView, ...]
    subviews: tuple[ExecutionView, ...]

    @classmethod
    def from_execution(
        cls,
        execution: ExecutedTest,
        *,
        verbosity: int = 0,
        title: str | None = None,
    ) -> ExecutionView:
        """Project execution results into terminal display state."""
        spec = execution.definition.spec
        label = spec.get_label(full=verbosity >= 2) or "case"
        summary = ""
        if spec.modifiers and execution.sub_executions:
            summary = spec.modifiers[0].display_summary
        status = execution.result.status
        fallback_title = spec.get_label(full=verbosity >= 2)
        return cls(
            label=label,
            local_name=spec.local_name,
            title=title or fallback_title or execution.label,
            status=status,
            status_style=STATUS_STYLES[status],
            duration_ms=execution.result.duration_ms,
            status_repr=execution.result.status_repr,
            modifier_suffix=f" {summary}" if summary else "",
            error=execution.result.error,
            failed_assertions=tuple(
                AssertionView.from_result(assertion)
                for assertion in execution.result.assertion_results
                if not assertion.passed
            ),
            subviews=tuple(
                cls.from_execution(sub, verbosity=verbosity)
                for sub in execution.sub_executions
            ),
        )

    @classmethod
    def render_assertion_failures(
        cls,
        failures: list[ExecutedTest],
        verbosity: int,
    ) -> list[RenderableType]:
        """Render assertion-only failure panels for top-level failures."""
        relevant = [
            view
            for view in (
                cls.from_execution(
                    failure,
                    title=failure.definition.spec.full_name,
                    verbosity=verbosity,
                )
                for failure in failures
            )
            if view.has_failed_assertions
        ]
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
            renderables.append(failure.assertion_panel())
        renderables.append(Text(""))
        return renderables

    @classmethod
    def render_exception_failures(
        cls,
        failures: list[ExecutedTest],
        verbosity: int,
        *,
        show_locals: bool = False,
    ) -> list[RenderableType]:
        """Render exception traceback panels for top-level failures."""
        relevant = [
            view
            for view in (
                cls.from_execution(
                    failure,
                    title=failure.definition.spec.full_name,
                    verbosity=verbosity,
                )
                for failure in failures
            )
            if view.has_exception
        ]
        if not relevant:
            return []
        renderables: list[RenderableType] = [
            Text(""),
            Rule(
                Text("ERRORS", style="bold red"),
                characters="=",
                style="red",
            ),
        ]
        for index, failure in enumerate(relevant):
            if index:
                renderables.append(Text(""))
            renderables.append(failure.exception_panel(show_locals=show_locals))
        renderables.append(Text(""))
        return renderables

    @property
    def should_show_error(self) -> bool:
        if self.error is None:
            return False
        if self.status is TestStatus.NOT_RUN:
            return False
        return not (
            isinstance(self.error, AssertionError)
            and bool(self.failed_assertions)
        )

    @property
    def has_exception(self) -> bool:
        return self.should_show_error or any(
            subview.has_exception for subview in self.subviews
        )

    @property
    def has_failed_assertions(self) -> bool:
        return bool(self.failed_assertions) or any(
            subview.has_failed_assertions for subview in self.subviews
        )

    @property
    def assertion_subviews(self) -> tuple[ExecutionView, ...]:
        return tuple(
            subview
            for subview in self.subviews
            if subview.has_failed_assertions
        )

    @property
    def exception_subviews(self) -> tuple[ExecutionView, ...]:
        return tuple(
            subview for subview in self.subviews if subview.has_exception
        )

    def assertion_panel(self) -> Panel:
        """Render nested failed assertions under this execution."""
        renderables: list[RenderableType] = []

        if self.failed_assertions:
            combined = Text()
            for i, assertion in enumerate(self.failed_assertions):
                if i:
                    combined.append("\n\n")
                combined.append_text(assertion.render("Failed Assertion"))
            renderables.append(combined)

        renderables.extend(
            subview.assertion_panel()
            for subview in self.assertion_subviews
        )
        return self._panel(renderables)

    def exception_panel(self, *, show_locals: bool = False) -> Panel:
        """Render nested exception tracebacks under this execution."""
        renderables: list[RenderableType] = []

        if self.should_show_error:
            err = self.error
            assert err is not None
            if err.__traceback__:
                renderables.append(
                    Traceback.from_exception(
                        type(err),
                        err,
                        err.__traceback__,
                        suppress=[_RUE_MODULE],
                        show_locals=show_locals,
                    )
                )
            else:
                renderables.append(escape(f"{type(err).__name__}: {err}"))

        renderables.extend(
            subview.exception_panel(show_locals=show_locals)
            for subview in self.exception_subviews
        )
        return self._panel(renderables)

    def render_test_line(
        self,
        *,
        name: str | None = None,
        extra: str = "",
        indent: int = 2,
        sub: bool = False,
    ) -> Text:
        """Render one completed test line for non-live output."""
        label = name or (self.label if sub else self.local_name)
        text = Text(" " * indent + "• ")
        text.append_text(
            self.sub_label_text(label) if sub else self.test_name_text(label)
        )
        if self.modifier_suffix:
            text.append(self.modifier_suffix, style=_MODIFIER_STYLE)
        text.append(f" ({self.duration_ms:.1f}ms)", style="dim")
        if extra:
            text.append(f" {extra}", style="dim")
        text.append(
            f" {self.status_style.label}", style=self.status_style.color
        )
        return text

    def render_live_item_line(self, *, name: str | None = None) -> Text:
        """Render one completed top-level node inside the live tree."""
        text = self.test_name_text(name or self.local_name)
        if self.modifier_suffix:
            text.append(self.modifier_suffix, style=_MODIFIER_STYLE)
        text.append(f" ({self.duration_ms:.1f}ms)", style="dim")
        if self.status_repr:
            text.append(f" {self.status_repr}", style="dim")
        text.append(
            f" {self.status_style.label}", style=self.status_style.color
        )
        return text

    def render_sub_live_line(self) -> Text:
        """Render one completed child node inside the live tree."""
        text = self.sub_label_text(self.label)
        if self.modifier_suffix:
            text.append(self.modifier_suffix, style=_MODIFIER_STYLE)
        text.append(f" ({self.duration_ms:.1f}ms)", style="dim")
        text.append(
            f" {self.status_style.label}", style=self.status_style.color
        )
        return text

    def _panel(self, renderables: list[RenderableType]) -> Panel:
        panel_content: RenderableType
        match renderables:
            case []:
                panel_content = " "
            case [single]:
                panel_content = single
            case _:
                panel_content = Group(*renderables)

        return Panel(
            panel_content,
            title=Text(
                self.title,
                style=f"bold {self.status_style.color}",
            ),
            title_align="left",
            border_style=self.status_style.color,
            expand=True,
            padding=(1, 1),
        )

    @staticmethod
    def running_line(name: str) -> Text:
        text = ExecutionView.test_name_text(name)
        text.append("  ")
        text.append("⋯ running", style="dim")
        return text

    @staticmethod
    def test_name_text(name: str) -> Text:
        text = Text()
        if "::" in name:
            prefix, _, func = name.rpartition("::")
            text.append(f"{prefix}::", style="dim")
            text.append(func, style="bold")
        else:
            text.append(name, style="bold")
        return text

    @staticmethod
    def sub_label_text(label: str) -> Text:
        if label.startswith("[") and label.endswith("]"):
            return Text(label)
        text = Text()
        text.append("[", style="dim")
        text.append(label)
        text.append("]", style="dim")
        return text




__all__ = [
    "AssertionView",
    "ExecutionView",
    "RunView",
]
