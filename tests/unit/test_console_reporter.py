"""Tests for rue.reports.console module."""

import io
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from rich.console import Console

from rue.assertions.base import AssertionRepr, AssertionResult
from rue.reports.console import ConsoleReporter
from rue.reports.console.metrics import MetricGroup
from rue.resources import ResourceSpec, Scope
from rue.resources.metrics.base import (
    MetricMetadata,
    MetricResult,
)
from rue.resources.sut.output import SUTOutputCapture
from rue.testing.execution.types import ExecutionBackend
from rue.testing.models import (
    IterateModifier,
    Run,
    LoadedTestDef,
    ExecutedTest,
    TestResult,
    TestStatus,
)
from tests.unit.factories import make_definition


class FakeLive:
    """Minimal stand-in for rich.live.Live used by unit tests."""

    instances: list["FakeLive"] = []

    def __init__(
        self,
        renderable,
        *,
        console: Console,
        auto_refresh: bool,
        refresh_per_second: int,
        transient: bool,
        redirect_stdout: bool = True,
        redirect_stderr: bool = True,
    ) -> None:
        self.console = console
        self.auto_refresh = auto_refresh
        self.refresh_per_second = refresh_per_second
        self.transient = transient
        self.redirect_stdout = redirect_stdout
        self.redirect_stderr = redirect_stderr
        self.started = False
        self.stopped = False
        self.renderables = [renderable]
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def update(self, renderable, *, refresh: bool = False) -> None:
        _ = refresh
        self.renderables.append(renderable)


def make_item(
    name: str,
    module_path: str,
    *,
    suffix: str | None = None,
    case_id: UUID | None = None,
) -> LoadedTestDef:
    return make_definition(
        name, module_path=module_path, suffix=suffix, case_id=case_id
    )


def make_execution(
    item: LoadedTestDef,
    status: TestStatus,
    duration_ms: float,
    *,
    error: Exception | None = None,
    assertion_results: list[AssertionResult] | None = None,
    sub_executions: list[ExecutedTest] | None = None,
) -> ExecutedTest:
    return ExecutedTest(
        definition=item,
        result=TestResult(
            status=status,
            duration_ms=duration_ms,
            error=error,
            assertion_results=assertion_results or [],
        ),
        sub_executions=sub_executions or [],
    )


def render_to_text(renderable) -> str:
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    console.print(renderable)
    return output.getvalue()


def make_metric_result(
    name: str,
    *,
    scope: Scope = Scope.PROCESS,
    value=1.0,
    assertion_results: list[AssertionResult] | None = None,
    tests: set[str] | None = None,
    resources: set[str] | None = None,
    cases: set[str] | None = None,
    modules: set[str] | None = None,
    provider_path: str | None = None,
    provider_dir: str | None = None,
    depends_on: list[ResourceSpec] | None = None,
    execution_id: UUID | None = None,
) -> MetricResult:
    metadata = MetricMetadata(
        identity=ResourceSpec(
            name=name,
            scope=scope,
            provider_path=provider_path,
            provider_dir=provider_dir,
        ),
        collected_from_tests=tests or set(),
        collected_from_resources=resources or set(),
        collected_from_cases=cases or set(),
        collected_from_modules=modules or set(),
    )
    return MetricResult(
        metadata=metadata,
        assertion_results=assertion_results or [],
        value=value,
        dependencies=depends_on or [],
        execution_id=execution_id,
    )


@pytest.mark.asyncio
async def test_verbose_live_output_grouped_by_file(monkeypatch):
    monkeypatch.setattr("rue.reports.console.reporter.Live", FakeLive)
    FakeLive.instances.clear()

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=True, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    auth_login = make_item("test_login", "tests/test_auth.py")
    auth_logout = make_item("test_logout", "tests/test_auth.py")
    users_create = make_item("test_create", "tests/test_users.py")

    await reporter.on_collection_complete(
        [auth_login, auth_logout, users_create], Run()
    )
    await reporter.on_test_start(auth_login)
    await reporter.on_test_start(users_create)
    await reporter.on_execution_complete(
        make_execution(users_create, TestStatus.PASSED, 45.1)
    )
    await reporter.on_execution_complete(
        make_execution(
            auth_login, TestStatus.FAILED, 120.3, error=AssertionError("boom")
        )
    )
    await reporter.on_test_start(auth_logout)
    await reporter.on_execution_complete(
        make_execution(auth_logout, TestStatus.PASSED, 22.0)
    )

    assert FakeLive.instances
    assert FakeLive.instances[-1].redirect_stdout is False
    assert FakeLive.instances[-1].redirect_stderr is False

    # Both modules completed → both promoted to static output; Live is empty.
    live_text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "tests/test_auth.py" not in live_text
    assert "tests/test_users.py" not in live_text

    static_text = output.getvalue()
    assert "tests/test_auth.py" in static_text
    assert "tests/test_users.py" in static_text
    assert "test_auth::test_login" in static_text
    assert "test_auth::test_logout" in static_text
    assert "test_users::test_create" in static_text
    assert "FAILED" in static_text


@pytest.mark.asyncio
async def test_verbose_live_partial_module_promotion(monkeypatch):
    """Completed modules are promoted to static output while pending ones stay in Live."""
    monkeypatch.setattr("rue.reports.console.reporter.Live", FakeLive)
    FakeLive.instances.clear()

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=True, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    auth_login = make_item("test_login", "tests/test_auth.py")
    auth_logout = make_item("test_logout", "tests/test_auth.py")
    users_create = make_item("test_create", "tests/test_users.py")

    await reporter.on_collection_complete(
        [auth_login, auth_logout, users_create], Run()
    )
    await reporter.on_test_start(users_create)

    # Complete the users module while auth module is still running.
    await reporter.on_execution_complete(
        make_execution(users_create, TestStatus.PASSED, 45.1)
    )

    # users module is done → promoted to static; auth module still in Live.
    static_text = output.getvalue()
    live_text = render_to_text(FakeLive.instances[-1].renderables[-1])

    assert "tests/test_users.py" in static_text
    assert "tests/test_users.py" not in live_text
    assert "tests/test_auth.py" in live_text


@pytest.mark.asyncio
async def test_compact_live_symbols_replace_running_marker(monkeypatch):
    monkeypatch.setattr("rue.reports.console.reporter.Live", FakeLive)
    FakeLive.instances.clear()

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=True, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=0)

    item = make_item("test_login", "tests/test_auth.py")

    await reporter.on_collection_complete([item], Run())
    await reporter.on_test_start(item)
    running_text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "⋯" in running_text

    await reporter.on_execution_complete(
        make_execution(item, TestStatus.PASSED, 15.0)
    )
    # Module is complete → promoted to static output; Live is now empty.
    live_text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "⋯" not in live_text
    assert "✓" in output.getvalue()


@pytest.mark.asyncio
async def test_quiet_live_progress_counter(monkeypatch):
    monkeypatch.setattr("rue.reports.console.reporter.Live", FakeLive)
    FakeLive.instances.clear()

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=True, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=-1)

    first = make_item("test_one", "tests/test_progress.py")
    second = make_item("test_two", "tests/test_progress.py")

    await reporter.on_collection_complete([first, second], Run())
    text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "0/2 complete" in text

    await reporter.on_test_start(first)
    await reporter.on_execution_complete(
        make_execution(first, TestStatus.PASSED, 5.0)
    )
    text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "1/2 complete" in text

    await reporter.on_test_start(second)
    await reporter.on_execution_complete(
        make_execution(second, TestStatus.PASSED, 6.0)
    )
    # All modules complete → live display clears.
    text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "complete" not in text


@pytest.mark.asyncio
async def test_non_terminal_fallback_uses_static_output():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=0)

    item = make_item("test_login", "tests/test_auth.py")
    execution = make_execution(item, TestStatus.PASSED, 20.0)

    await reporter.on_collection_complete([item], Run())
    await reporter.on_test_start(item)
    await reporter.on_execution_complete(execution)

    test_run = Run()
    test_run.result.executions = [execution]
    await reporter.on_run_complete(test_run)

    text = output.getvalue()
    assert "Collected 1 tests" in text
    assert "tests/test_auth.py" in text
    assert "SUMMARY" in text


@pytest.mark.asyncio
async def test_nested_failures_render_leaf_assertion_repr():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    parent = make_item("test_nested", "tests/test_nested.py")
    repeated = make_item(
        "test_nested", "tests/test_nested.py", suffix="iterate=0"
    )
    leaf = make_item("test_nested", "tests/test_nested.py", suffix="case=1")
    assertion = AssertionResult(
        expression_repr=AssertionRepr(
            expr="left == right",
            lines_above="",
            lines_below="",
            resolved_args={"left": "1", "right": "2"},
        ),
        passed=False,
        error_message="values differ",
    )
    leaf_execution = make_execution(
        leaf,
        TestStatus.FAILED,
        8.0,
        assertion_results=[assertion],
    )
    repeated_execution = make_execution(
        repeated,
        TestStatus.FAILED,
        12.0,
        sub_executions=[leaf_execution],
    )
    execution = make_execution(
        parent,
        TestStatus.FAILED,
        20.0,
        sub_executions=[repeated_execution],
    )

    await reporter.on_collection_complete([parent], Run())
    await reporter.on_execution_complete(execution)

    test_run = Run()
    test_run.result.executions = [execution]
    await reporter.on_run_complete(test_run)

    text = output.getvalue()
    assert "ASSERTIONS" in text
    assert "iterate=0" in text
    assert "case=1" in text
    assert "left == right" in text
    assert "values differ" in text
    assert "where:" in text
    assert "left = 1" in text
    assert "right = 2" in text


@pytest.mark.asyncio
async def test_exception_only_renders_errors_section():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    item = make_item("test_crash", "tests/test_crash.py")
    execution = make_execution(
        item,
        TestStatus.ERROR,
        5.0,
        error=RuntimeError("connection reset"),
    )

    await reporter.on_collection_complete([item], Run())
    await reporter.on_execution_complete(execution)

    test_run = Run()
    test_run.result.executions = [execution]
    await reporter.on_run_complete(test_run)

    text = output.getvalue()
    assert "ERRORS" in text
    assert "ASSERTIONS" not in text
    assert "RuntimeError" in text
    assert "connection reset" in text


@pytest.mark.asyncio
async def test_mixed_assertion_and_exception_renders_both_sections_ordered():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    item = make_item("test_mixed", "tests/test_mixed.py")
    assertion = AssertionResult(
        expression_repr=AssertionRepr(
            expr="x == 1",
            lines_above="",
            lines_below="",
            resolved_args={"x": "2"},
        ),
        passed=False,
        error_message="expected one",
    )
    execution = make_execution(
        item,
        TestStatus.ERROR,
        10.0,
        error=RuntimeError("then crashed"),
        assertion_results=[assertion],
    )

    await reporter.on_collection_complete([item], Run())
    await reporter.on_execution_complete(execution)

    test_run = Run()
    test_run.result.executions = [execution]
    await reporter.on_run_complete(test_run)

    text = output.getvalue()
    assert "ASSERTIONS" in text
    assert "ERRORS" in text
    assert text.index("ASSERTIONS") < text.index("ERRORS")
    assert "x == 1" in text
    assert "expected one" in text
    assert "RuntimeError" in text
    assert "then crashed" in text


@pytest.mark.asyncio
async def test_verbose_live_renders_sub_executions(monkeypatch):
    monkeypatch.setattr("rue.reports.console.reporter.Live", FakeLive)
    FakeLive.instances.clear()

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=True, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    parent = make_item("test_matrix", "tests/test_matrix.py")
    case_one = make_item("test_matrix", "tests/test_matrix.py", suffix="case=1")
    case_two = make_item("test_matrix", "tests/test_matrix.py", suffix="case=2")

    sub_executions = [
        make_execution(case_one, TestStatus.PASSED, 8.0),
        make_execution(
            case_two, TestStatus.FAILED, 12.0, error=AssertionError("bad case")
        ),
    ]
    execution = make_execution(
        parent,
        TestStatus.FAILED,
        20.0,
        sub_executions=sub_executions,
    )

    await reporter.on_collection_complete([parent], Run())
    await reporter.on_test_start(parent)
    await reporter.on_execution_complete(execution)

    # Module is complete → promoted to static output; Live is empty.
    live_text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "case=1" not in live_text

    static_text = output.getvalue()
    assert "case=1" in static_text
    assert "case=2" in static_text
    assert "FAILED" in static_text
    assert "↳" not in static_text
    assert "2/2 passed" not in static_text


@pytest.mark.asyncio
async def test_very_verbose_mode_shows_captured_stderr_as_warnings_section():
    import sys

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=2)

    item = make_item("test_foo", "tests/test_foo.py")
    execution = make_execution(item, TestStatus.PASSED, 10.0)

    with SUTOutputCapture.sys_capture(swallow=False):
        await reporter.on_collection_complete([item], Run())
        sys.stderr.write("some noisy warning\n")
        await reporter.on_execution_complete(execution)

        test_run = Run()
        test_run.result.executions = [execution]
        await reporter.on_run_complete(test_run)

    text = output.getvalue()
    assert "WARNINGS" in text
    assert "some noisy warning" in text
    assert "SUMMARY" in text
    assert text.index("WARNINGS") < text.index("SUMMARY")


@pytest.mark.asyncio
async def test_compact_mode_does_not_show_warnings_section():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=0)

    item = make_item("test_foo", "tests/test_foo.py")
    execution = make_execution(item, TestStatus.PASSED, 10.0)

    await reporter.on_collection_complete([item], Run())
    import sys

    sys.stderr.write("some noisy warning\n")
    await reporter.on_execution_complete(execution)

    test_run = Run()
    test_run.result.executions = [execution]
    await reporter.on_run_complete(test_run)

    assert "WARNINGS" not in output.getvalue()


@pytest.mark.asyncio
async def test_verbose_mode_does_not_show_warnings_section():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    item = make_item("test_foo", "tests/test_foo.py")
    execution = make_execution(item, TestStatus.PASSED, 10.0)

    await reporter.on_collection_complete([item], Run())
    import sys

    sys.stderr.write("some noisy warning\n")
    await reporter.on_execution_complete(execution)

    test_run = Run()
    test_run.result.executions = [execution]
    await reporter.on_run_complete(test_run)

    assert "WARNINGS" not in output.getvalue()


@pytest.mark.asyncio
async def test_very_verbose_mode_collapses_duplicate_warnings():
    import sys

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=2)

    item = make_item("test_foo", "tests/test_foo.py")
    execution = make_execution(item, TestStatus.PASSED, 10.0)

    with SUTOutputCapture.sys_capture(swallow=False):
        await reporter.on_collection_complete([item], Run())
        for _ in range(3):
            sys.stderr.write("repeated warning\n")
        sys.stderr.write("unique warning\n")
        await reporter.on_execution_complete(execution)

        test_run = Run()
        test_run.result.executions = [execution]
        await reporter.on_run_complete(test_run)

    text = output.getvalue()
    assert text.count("repeated warning") == 1
    assert "(x3)" in text
    assert "unique warning" in text
    assert "(x1)" not in text


@pytest.mark.asyncio
async def test_verbose_live_streams_subtests_before_parent_completion(
    monkeypatch,
):
    monkeypatch.setattr("rue.reports.console.reporter.Live", FakeLive)
    FakeLive.instances.clear()

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=True, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    parent = make_item("test_matrix", "tests/test_matrix.py")
    case_one = replace(parent, spec=replace(parent.spec, suffix="case=1"))
    sub_execution = make_execution(case_one, TestStatus.PASSED, 8.0)

    await reporter.on_collection_complete([parent], Run())
    await reporter.on_test_start(parent)
    await reporter.on_execution_complete(sub_execution)

    text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "test_matrix::test_matrix" in text
    assert "running" in text
    assert "case=1" in text
    assert "↳" not in text


@pytest.mark.asyncio
async def test_verbose_live_backend_wrapped_single_completes_top_level(
    monkeypatch,
):
    monkeypatch.setattr("rue.reports.console.reporter.Live", FakeLive)
    FakeLive.instances.clear()

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=True, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    item = make_definition(
        "test_sync_inline",
        module_path="tests/test_backends.py",
        backend=ExecutionBackend.MAIN,
    )
    executed_item = replace(item, spec=replace(item.spec, modifiers=()))

    await reporter.on_collection_complete([item], Run())
    await reporter.on_test_start(item)
    await reporter.on_execution_complete(
        make_execution(executed_item, TestStatus.PASSED, 5.0)
    )

    live_text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "running" not in live_text

    static_text = output.getvalue()
    assert "tests/test_backends.py" in static_text
    assert "test_backends::test_sync_inline" in static_text
    assert "PASSED" in static_text


@pytest.mark.asyncio
async def test_verbose_live_backend_wrapped_composite_clears_after_parent(
    monkeypatch,
):
    monkeypatch.setattr("rue.reports.console.reporter.Live", FakeLive)
    FakeLive.instances.clear()

    output = io.StringIO()
    console = Console(
        file=output, force_terminal=True, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    item = make_definition(
        "test_subprocess_iterations",
        module_path="tests/test_backends.py",
        backend=ExecutionBackend.SUBPROCESS,
        modifiers=(IterateModifier(count=2, min_passes=2),),
    )
    executed_item = replace(
        item, spec=replace(item.spec, modifiers=item.spec.modifiers[1:])
    )
    case_one = replace(
        executed_item,
        spec=replace(executed_item.spec, modifiers=(), suffix="iterate=0"),
    )
    case_execution = make_execution(case_one, TestStatus.PASSED, 8.0)

    await reporter.on_collection_complete([item], Run())
    await reporter.on_test_start(item)
    await reporter.on_execution_complete(case_execution)

    running_text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "test_backends::test_subprocess_iterations" in running_text
    assert "iterate=0" in running_text

    await reporter.on_execution_complete(
        make_execution(
            executed_item,
            TestStatus.PASSED,
            8.0,
            sub_executions=[case_execution],
        )
    )

    live_text = render_to_text(FakeLive.instances[-1].renderables[-1])
    assert "running" not in live_text

    static_text = output.getvalue()
    assert "test_backends::test_subprocess_iterations" in static_text
    assert "iterate=0" in static_text
    assert "PASSED" in static_text


@pytest.mark.asyncio
async def test_metrics_compact_mode_shows_threshold_snippets_only():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=0)

    assertion = AssertionResult(
        expression_repr=AssertionRepr(
            expr="assert metric.mean > 0.8",
            lines_above="",
            lines_below="",
            resolved_args={"metric.mean": "0.91"},
        ),
        passed=True,
    )
    run = Run()
    run.result.metric_results = [
        make_metric_result(
            "accuracy",
            assertion_results=[assertion],
            modules={"tests/rue_accuracy.py"},
            tests={"test_accuracy"},
            provider_path="/tmp/project/confrue_root.py",
            provider_dir="/tmp/project",
        )
    ]

    await reporter.on_run_complete(run)

    text = output.getvalue()
    assert "OVERVIEW" in text
    assert "BREAKDOWN" not in text
    assert "mean / 0.91 > 0.8" in text
    assert "1/1" not in text
    assert "Instances" not in text
    assert "Modules" not in text


@pytest.mark.asyncio
async def test_metrics_verbose_mode_groups_case_metrics_into_instances_panel():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    passing = AssertionResult(
        expression_repr=AssertionRepr(
            expr="assert metric.mean > 0.8",
            lines_above="",
            lines_below="",
            resolved_args={"metric.mean": "1.0"},
        ),
        passed=True,
    )
    failing = AssertionResult(
        expression_repr=AssertionRepr(
            expr="assert metric.mean > 0.8",
            lines_above="",
            lines_below="",
            resolved_args={"metric.mean": "0.0"},
        ),
        passed=False,
        error_message="below threshold",
    )
    run = Run()
    run.result.metric_results = [
        make_metric_result(
            "case_accuracy",
            scope=Scope.TEST,
            value=1.0,
            assertion_results=[passing],
            tests={"test_shared"},
            cases={"case-a"},
            modules={"tests/rue_cases.py"},
            provider_path="/tmp/project/confrue_root.py",
            provider_dir="/tmp/project",
            execution_id=UUID(int=1),
        ),
        make_metric_result(
            "case_accuracy",
            scope=Scope.TEST,
            value=0.0,
            assertion_results=[failing],
            tests={"test_shared"},
            cases={"case-b"},
            modules={"tests/rue_cases.py"},
            provider_path="/tmp/project/confrue_root.py",
            provider_dir="/tmp/project",
            execution_id=UUID(int=2),
        ),
    ]

    await reporter.on_run_complete(run)

    text = output.getvalue()
    assert "OVERVIEW" in text
    assert "BREAKDOWN" in text
    assert "case_accuracy" in text
    assert "test ×2" in text
    assert "Instances" in text
    assert "[case-a]" in text
    assert "[case-b]" in text
    assert "Metric Assertion" in text
    assert "below threshold" in text


@pytest.mark.asyncio
async def test_metrics_verbose_mode_shows_modules_and_composite_tree():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    parent = make_metric_result(
        "overall_quality",
        value=0.92,
        modules={"tests/rue_positive.py", "tests/rue_negative.py"},
        tests={"test_shared"},
        provider_path="/tmp/project/confrue_root.py",
        provider_dir="/tmp/project",
    )
    child = make_metric_result(
        "accuracy",
        value=0.92,
        assertion_results=[
            AssertionResult(
                expression_repr=AssertionRepr(
                    expr="assert metric.mean > 0.8",
                    lines_above="",
                    lines_below="",
                    resolved_args={"metric.mean": "0.92"},
                ),
                passed=True,
            )
        ],
        modules={"tests/rue_positive.py", "tests/rue_negative.py"},
        tests={"test_shared"},
        resources={"false_negatives", "false_positives"},
        provider_path="/tmp/project/confrue_root.py",
        provider_dir="/tmp/project",
        depends_on=[parent.metadata.identity],
    )
    run = Run()
    run.result.metric_results = [parent, child]

    await reporter.on_run_complete(run)

    text = output.getvalue()
    assert "OVERVIEW" in text
    assert "BREAKDOWN" in text
    assert "Hierarchy" in text
    assert "Path" in text
    assert "overall_quality" in text
    assert "accuracy" in text
    assert "tests/rue_positive.py" in text
    assert "tests/rue_negative.py" in text
    assert "false_negatives" in text
    assert "false_positives" in text
    assert "Contributors" in text
    assert "Instances" in text
    assert "Assertions" in text


@pytest.mark.asyncio
async def test_metrics_overview_disambiguates_same_name_providers():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=0)

    run = Run()
    run.result.metric_results = [
        make_metric_result(
            "quality",
            provider_path="/tmp/project/confrue_root.py",
            provider_dir="/tmp/project",
        ),
        make_metric_result(
            "quality",
            provider_path="/tmp/project/child/confrue_child.py",
            provider_dir="/tmp/project/child",
        ),
    ]

    await reporter.on_run_complete(run)

    text = output.getvalue()
    assert "OVERVIEW" in text
    assert "quality @ /tmp/project/confrue_root.py" in text
    assert "quality @ /tmp/project/child/confrue_child.py" in text


@pytest.mark.asyncio
async def test_metrics_verbose_mode_truncates_long_instance_labels():
    output = io.StringIO()
    console = Console(
        file=output, force_terminal=False, color_system=None, width=120
    )
    reporter = ConsoleReporter(console=console, verbosity=1)

    long_path = "/tmp/project/some/really/long/path/confrue_metrics_root.py"
    run = Run()
    run.result.metric_results = [
        make_metric_result(
            "long_label_metric",
            modules={"tests/rue_alpha.py", "tests/rue_beta.py"},
            provider_path=long_path,
            provider_dir="/tmp/project/some/really/long/path",
        )
    ]

    await reporter.on_run_complete(run)

    text = output.getvalue()
    assert "long_label_metric" in text
    assert "/tmp/project/some/really/lon…" in text


def test_metrics_overview_assertion_summary_substitutes_resolved_value_with_dim_label():
    reporter = ConsoleReporter(verbosity=0)
    assertion = AssertionResult(
        expression_repr=AssertionRepr(
            expr="assert metric.distribution[True] > 0.8",
            lines_above="",
            lines_below="",
            resolved_args={"metric.distribution[True]": "0.5"},
        ),
        passed=True,
    )
    group = MetricGroup(
        key=ResourceSpec(name="accuracy", scope=Scope.PROCESS),
        metrics=[],
    )
    group.metrics = [
        make_metric_result(
            "accuracy",
            assertion_results=[assertion],
        )
    ]

    summary = reporter._metrics._assertion_summary(group)

    assert summary.plain == "distribution[True] / 0.5 > 0.8"
    assert any(span.style == "grey62" for span in summary.spans)
