"""Tests for rue.testing.runner module."""

import asyncio
import builtins
import json
import os
import time
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from rue import SUT
from rue.config import Config
from rue.reports import OtelReporter
from rue.reports.base import Reporter
from rue.reports.otel import DEFAULT_OTEL_OUTPUT_ROOT, MAX_STORED_OTEL_RUNS
from rue.resources import ResourceRegistry, registry, resource
from rue.resources.sut import sut
from rue.telemetry.otel.runtime import OtelTraceSession, otel_runtime
from rue.testing.environment import _filter_env_vars
from rue.testing.models import (
    ParameterSet,
    ParamsIterateModifier,
    RunResult,
    ExecutedTest,
    LoadedTestDef,
    TestResult,
    TestStatus,
)
from rue.testing.runner import Runner
from tests.unit.factories import make_definition, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the global registry before and after each test."""
    registry.reset()
    yield
    registry.reset()


def make_item(
    fn,
    name: str | None = None,
    is_async: bool = False,
    params: list[str] | None = None,
    skip_reason: str | None = None,
    xfail_reason: str | None = None,
    xfail_strict: bool = False,
    suffix: str | None = None,
    case_id: UUID | None = None,
) -> LoadedTestDef:
    """Helper to create LoadedTestDef for testing."""
    return make_definition(
        name or fn.__name__,
        fn=fn,
        is_async=is_async,
        params=params or [],
        skip_reason=skip_reason,
        xfail_reason=xfail_reason,
        xfail_strict=xfail_strict,
        suffix=suffix,
        case_id=case_id,
    )


def make_runner_config(**kwargs) -> Config:
    return Config.model_construct(**kwargs)


class EventReporter(Reporter):
    """Reporter that records event timing and sequencing."""

    def __init__(self) -> None:
        self.start_time = 0.0
        self.verbosity = 0
        self.event_times: list[tuple[str, str, float]] = []
        self.event_order: list[tuple[str, str]] = []
        self.subtest_event_times: list[tuple[str, str, float]] = []
        self.trace_events: list[tuple[UUID, OtelTraceSession]] = []
        self.run_complete_elapsed = 0.0
        self._started_ids: set[int] = set()

    def configure(self, config: Config) -> None:
        self.verbosity = config.verbosity

    async def on_no_tests_found(self) -> None:
        pass

    async def on_collection_complete(
        self, _items: list[LoadedTestDef], _run
    ) -> None:
        self.start_time = time.perf_counter()

    async def on_test_start(self, item: LoadedTestDef) -> None:
        self._started_ids.add(id(item))
        elapsed = time.perf_counter() - self.start_time
        self.event_times.append(("start", item.spec.name, elapsed))
        self.event_order.append(("start", item.spec.name))

    async def on_execution_complete(self, execution: ExecutedTest) -> None:
        elapsed = time.perf_counter() - self.start_time
        if id(execution.definition) in self._started_ids:
            self.event_times.append(
                ("complete", execution.definition.spec.name, elapsed)
            )
            self.event_order.append(
                ("complete", execution.definition.spec.name)
            )
        else:
            label = execution.definition.spec.suffix or (
                str(execution.definition.spec.case_id)
                if execution.definition.spec.case_id
                else ""
            )
            self.subtest_event_times.append(
                (execution.definition.spec.name, label, elapsed)
            )

    async def on_run_complete(self, _rue_run) -> None:
        self.run_complete_elapsed = time.perf_counter() - self.start_time

    async def on_run_stopped_early(self, failure_count: int) -> None:
        pass

    async def on_trace_collected(self, tracer, execution_id: UUID) -> None:
        if tracer.completed_otel_trace_session is not None:
            self.trace_events.append(
                (execution_id, tracer.completed_otel_trace_session)
            )


class TestRunResult:
    """Tests for RunResult dataclass."""

    def test_counts_all_statuses(self):
        result = RunResult()
        items = [make_item(lambda: None) for _ in range(6)]
        result.executions = [
            ExecutedTest(
                definition=items[0],
                result=TestResult(status=TestStatus.PASSED, duration_ms=1),
            ),
            ExecutedTest(
                definition=items[1],
                result=TestResult(status=TestStatus.FAILED, duration_ms=1),
            ),
            ExecutedTest(
                definition=items[2],
                result=TestResult(status=TestStatus.ERROR, duration_ms=1),
            ),
            ExecutedTest(
                definition=items[3],
                result=TestResult(status=TestStatus.SKIPPED, duration_ms=1),
            ),
            ExecutedTest(
                definition=items[4],
                result=TestResult(status=TestStatus.XFAILED, duration_ms=1),
            ),
            ExecutedTest(
                definition=items[5],
                result=TestResult(status=TestStatus.XPASSED, duration_ms=1),
            ),
        ]
        assert result.passed == 1
        assert result.failed == 1
        assert result.errors == 1
        assert result.skipped == 1
        assert result.xfailed == 1
        assert result.xpassed == 1


class TestEnvironmentCapture:
    """Tests for environment capture functionality."""

    def test_filter_env_vars_masks_keys(self):
        """Test that sensitive keys are masked."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-1234567890abcdef",
                "ANTHROPIC_API_KEY": "sk-ant-1234567890abcdef",
                "MODEL_VENDOR": "openai",
                "RANDOM_VAR": "should_not_be_captured",
            },
            clear=True,
        ):
            captured = _filter_env_vars()

            assert captured["MODEL_VENDOR"] == "openai"
            assert "RANDOM_VAR" not in captured
            assert captured["OPENAI_API_KEY"] == "***cdef"
            assert captured["ANTHROPIC_API_KEY"] == "***cdef"

    def test_filter_env_vars_short_keys(self):
        """Test masking of short keys."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "123"}, clear=True):
            captured = _filter_env_vars()
            assert captured["OPENAI_API_KEY"] == "***"


class TestRunner:
    """Tests for Runner class."""

    def test_uses_all_registered_reporters_when_not_specified(self):
        extra = EventReporter()
        runner = Runner(
            config=make_runner_config(db_enabled=False, verbosity=4)
        )

        assert runner.reporters[:2] == [
            Reporter.REGISTRY["ConsoleReporter"],
            Reporter.REGISTRY["OtelReporter"],
        ]
        assert runner.reporters[2] is extra
        assert extra.verbosity == 4

    def test_configures_provided_reporters(self):
        reporter = EventReporter()
        config = make_runner_config(db_enabled=False, verbosity=5)
        runner = Runner(config=config, reporters=[reporter])

        assert runner.reporters == [reporter]
        assert reporter.verbosity == 5

    def test_config_reporter_names_override_provided_instances(self):
        class SelectedReporter(EventReporter):
            pass

        class OtherReporter(EventReporter):
            pass

        selected = SelectedReporter()
        other = OtherReporter()
        config = make_runner_config(
            db_enabled=False, reporters=["SelectedReporter"]
        )

        runner = Runner(config=config, reporters=[other])

        assert runner.reporters == [selected]

    @pytest.mark.asyncio
    async def test_xfail_strict_fails_on_pass(self, null_reporter):
        def strict_xfail_test():
            pass

        item = make_item(
            strict_xfail_test, xfail_reason="must fail", xfail_strict=True
        )
        runner = Runner(reporters=[null_reporter])
        result = await runner.run(items=[item])

        assert result.result.failed == 1

    @pytest.mark.asyncio
    async def test_fail_fast_stops_after_first_rewritten_assertion(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        null_reporter,
    ):
        module_path = tmp_path / "test_fail_fast.py"
        module_path.write_text(
            dedent(
                """
                import builtins
                import rue

                @rue.test
                def test_fail_fast():
                    builtins.fail_fast_events.append("before")
                    assert False, "first failure"
                    builtins.fail_fast_events.append("after_first")
                    assert False, "second failure"
                """
            )
        )
        monkeypatch.setattr(builtins, "fail_fast_events", [], raising=False)

        result = await Runner(
            reporters=[null_reporter],
            fail_fast=True,
        ).run(items=materialize_tests(module_path))

        execution = result.result.executions[0]
        assert result.result.failed == 1
        assert builtins.fail_fast_events == ["before"]
        assert len(execution.result.assertion_results) == 1
        assert "first failure" in str(execution.result.error)


class TestRunId:
    @pytest.mark.asyncio
    async def test_constructor_run_id_used_when_run_id_not_passed(
        self, null_reporter
    ):
        run_id = uuid4()
        runner = Runner(
            config=make_runner_config(db_enabled=False),
            reporters=[null_reporter],
            run_id=run_id,
        )

        result = await runner.run(items=[make_item(lambda: None)])

        assert result.run_id == run_id

    @pytest.mark.asyncio
    async def test_run_run_id_overrides_constructor_run_id(self, null_reporter):
        constructor_run_id = uuid4()
        run_level_run_id = uuid4()
        runner = Runner(
            config=make_runner_config(db_enabled=False),
            reporters=[null_reporter],
            run_id=constructor_run_id,
        )

        result = await runner.run(
            items=[make_item(lambda: None)], run_id=run_level_run_id
        )

        assert result.run_id == run_level_run_id

    @pytest.mark.asyncio
    async def test_run_id_string_is_accepted_and_normalized(
        self, null_reporter
    ):
        run_id = uuid4()
        runner = Runner(
            config=make_runner_config(db_enabled=False),
            reporters=[null_reporter],
            run_id=str(run_id),
        )

        result = await runner.run(items=[make_item(lambda: None)])

        assert isinstance(result.run_id, UUID)
        assert result.run_id == run_id

    def test_invalid_constructor_run_id_raises_value_error(self, null_reporter):
        with pytest.raises(ValueError, match="Invalid run_id"):
            Runner(
                config=make_runner_config(db_enabled=False),
                reporters=[null_reporter],
                run_id="not-a-uuid",
            )

    @pytest.mark.asyncio
    async def test_invalid_run_level_run_id_raises_value_error(
        self, null_reporter
    ):
        runner = Runner(
            config=make_runner_config(db_enabled=False),
            reporters=[null_reporter],
        )

        with pytest.raises(ValueError, match="Invalid run_id"):
            await runner.run(
                items=[make_item(lambda: None)], run_id="not-a-uuid"
            )

    @pytest.mark.asyncio
    async def test_reused_constructor_run_id_fails_on_second_run_when_db_enabled(
        self, null_reporter, tmp_path: Path
    ):
        run_id = uuid4()
        runner = Runner(
            config=make_runner_config(db_path=tmp_path / "rue.db"),
            reporters=[null_reporter],
            run_id=run_id,
        )

        first_result = await runner.run(items=[make_item(lambda: None)])
        assert first_result.run_id == run_id

        with pytest.raises(ValueError, match="already exists"):
            await runner.run(items=[make_item(lambda: None)])

    @pytest.mark.asyncio
    async def test_reused_constructor_run_id_allowed_when_db_disabled(
        self, null_reporter
    ):
        run_id = uuid4()
        runner = Runner(
            config=make_runner_config(db_enabled=False),
            reporters=[null_reporter],
            run_id=run_id,
        )

        first_result = await runner.run(items=[make_item(lambda: None)])
        second_result = await runner.run(items=[make_item(lambda: None)])

        assert first_result.run_id == run_id
        assert second_result.run_id == run_id


class TestResourceInjection:
    """Tests for resource injection in runner."""

    @pytest.mark.asyncio
    async def test_injects_resource(self, null_reporter):
        @resource
        def injected():
            return "injected_value"

        captured = []

        def test_with_resource(injected):
            captured.append(injected)

        item = make_item(test_with_resource, params=["injected"])
        runner = Runner(reporters=[null_reporter])
        await runner.run(items=[item])

        assert captured == ["injected_value"]

    @pytest.mark.asyncio
    async def test_uses_provided_resource_registry(self, null_reporter):
        custom_resource_registry = ResourceRegistry()

        @custom_resource_registry.resource
        def injected():
            return "custom_value"

        captured = []

        def test_with_resource(injected):
            captured.append(injected)

        item = make_item(test_with_resource, params=["injected"])
        runner = Runner(
            reporters=[null_reporter],
            resource_registry=custom_resource_registry,
        )
        await runner.run(items=[item])

        assert captured == ["custom_value"]

    @pytest.mark.asyncio
    async def test_removed_otel_trace_resource_errors(self, null_reporter):
        def test_needs_trace(otel_trace):
            pass

        item = make_item(test_needs_trace, params=["otel_trace"])
        runner = Runner(reporters=[null_reporter])
        result = await runner.run(items=[item])

        assert result.result.errors == 1
        assert "Unknown resource: otel_trace" in str(
            result.result.executions[0].result.error
        )

    @pytest.mark.asyncio
    async def test_ignores_unknown_params(self, null_reporter):
        def test_unknown(unknown_param):
            pass

        item = make_item(test_unknown, params=["unknown_param"])
        runner = Runner(reporters=[null_reporter])
        result = await runner.run(items=[item])

        # Should error because unknown_param is not provided
        assert result.result.errors == 1

    @pytest.mark.parametrize("capture_output", [True, False])
    @pytest.mark.asyncio
    async def test_sut_output_respects_runner_capture_mode(
        self,
        capture_output: bool,
        capsys,
        null_reporter,
    ):
        captured = []

        @sut
        def agent():
            def run():
                print("hello from sut")

            return SUT(run)

        def test_output(agent):
            print("hello from test")
            agent.instance()
            captured.append((agent.stdout.text, agent.stderr.text))

        result = await Runner(
            reporters=[null_reporter],
            capture_output=capture_output,
        ).run(items=[make_item(test_output, params=["agent"])])

        assert result.result.passed == 1
        assert captured == [("hello from sut\n", "")]

        real_out, real_err = capsys.readouterr()
        assert real_err == ""
        assert "hello from test" in real_out
        if capture_output:
            assert "hello from sut" not in real_out
        else:
            assert "hello from test" in real_out
            assert "hello from sut" in real_out


class TestOpenTelemetry:
    """Tests for runner-managed tracing behavior."""

    @pytest.mark.asyncio
    async def test_concurrent_traced_tests_keep_spans_isolated(
        self,
    ):
        captured: dict[str, set[str]] = {}

        async def first():
            async def run() -> None:
                with otel_runtime.start_as_current_span("first_step"):
                    await asyncio.sleep(0.01)

            first_agent = SUT(run, name="first_agent")
            await first_agent.instance()
            captured["first"] = {span.name for span in first_agent.all_spans}

        async def second():
            async def run() -> None:
                with otel_runtime.start_as_current_span("second_step"):
                    await asyncio.sleep(0.01)

            second_agent = SUT(run, name="second_agent")
            await second_agent.instance()
            captured["second"] = {span.name for span in second_agent.all_spans}

        items = [
            make_item(first, name="test_first", is_async=True),
            make_item(second, name="test_second", is_async=True),
        ]

        reporter = EventReporter()
        runner = Runner(
            config=make_runner_config(
                concurrency=2,
                otel=True,
                db_enabled=False,
            ),
            reporters=[reporter],
        )
        result = await runner.run(items=items)

        assert result.result.passed == 2
        assert captured["first"] == {"sut.first_agent.__call__", "first_step"}
        assert captured["second"] == {
            "sut.second_agent.__call__",
            "second_step",
        }

        trace_ids = {
            session.root_span.get_span_context().trace_id
            for _, session in reporter.trace_events
        }
        assert len(trace_ids) == 2

        payloads_by_execution = {
            execution_id: session.serialize()
            for execution_id, session in reporter.trace_events
        }
        assert set(payloads_by_execution) == {
            execution.execution_id for execution in result.result.executions
        }
        for execution in result.result.executions:
            payload = payloads_by_execution[execution.execution_id]
            expected_child = (
                "first_step"
                if execution.definition.spec.name == "test_first"
                else "second_step"
            )
            assert {span["name"] for span in payload["spans"]} == {
                f"test.{execution.definition.spec.full_name}",
                (
                    "sut.first_agent.__call__"
                    if execution.definition.spec.name == "test_first"
                    else "sut.second_agent.__call__"
                ),
                expected_child,
            }

    @pytest.mark.asyncio
    async def test_reporter_receives_trace_events_without_auto_persistence(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        async def traced():
            with otel_runtime.start_as_current_span("session_step"):
                await asyncio.sleep(0)

        monkeypatch.chdir(tmp_path)
        reporter = EventReporter()
        result = await Runner(
            config=make_runner_config(otel=True, db_enabled=False),
            reporters=[reporter],
        ).run(
            items=[make_item(traced, name="test_trace_session", is_async=True)]
        )

        assert len(reporter.trace_events) == 1

        execution = result.result.executions[0]
        execution_id, session = reporter.trace_events[0]
        assert execution_id == execution.execution_id
        assert session.run_id == result.run_id
        assert session.execution_id == execution.execution_id
        assert not (tmp_path / DEFAULT_OTEL_OUTPUT_ROOT).exists()

    @pytest.mark.asyncio
    async def test_default_runner_collects_trace_session(
        self,
    ):
        reporter = EventReporter()
        result = await Runner(
            config=make_runner_config(db_enabled=False),
            reporters=[reporter],
        ).run(items=[make_item(lambda: None, name="test_without_otel")])

        assert result.result.passed == 1
        assert len(reporter.trace_events) == 1

    @pytest.mark.asyncio
    async def test_no_trace_session_notification_when_otel_disabled(
        self,
    ):
        reporter = EventReporter()
        result = await Runner(
            config=make_runner_config(otel=False, db_enabled=False),
            reporters=[reporter],
        ).run(items=[make_item(lambda: None, name="test_without_otel")])

        assert result.result.passed == 1
        assert reporter.trace_events == []

    @pytest.mark.asyncio
    async def test_aggregated_children_collect_traces_but_parent_does_not(
        self,
    ):
        async def test_case(value: int):
            _ = value
            await asyncio.sleep(0)

        item = make_definition(
            "test_params_trace",
            fn=test_case,
            is_async=True,
            params=["value"],
            modifiers=[
                ParamsIterateModifier(
                    parameter_sets=(
                        ParameterSet(values={"value": 1}, suffix="one"),
                        ParameterSet(values={"value": 2}, suffix="two"),
                    ),
                    min_passes=2,
                )
            ],
        )

        reporter = EventReporter()
        result = await Runner(
            config=make_runner_config(otel=True, db_enabled=False),
            reporters=[reporter],
        ).run(items=[item])

        execution = result.result.executions[0]
        child_execution_ids = {
            sub.execution_id for sub in execution.sub_executions
        }

        assert len(child_execution_ids) == 2
        assert execution.execution_id not in child_execution_ids
        assert {
            execution_id for execution_id, _ in reporter.trace_events
        } == child_execution_ids
        assert all(
            execution_id == session.execution_id
            for execution_id, session in reporter.trace_events
        )

    @pytest.mark.asyncio
    async def test_otel_reporter_writes_to_hardcoded_run_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        async def traced():
            with otel_runtime.start_as_current_span("default_step"):
                await asyncio.sleep(0)

        monkeypatch.chdir(tmp_path)
        result = await Runner(
            config=make_runner_config(otel=True, db_enabled=False),
            reporters=[OtelReporter()],
        ).run(
            items=[make_item(traced, name="test_default_trace", is_async=True)]
        )

        execution = result.result.executions[0]
        run_dir = tmp_path / DEFAULT_OTEL_OUTPUT_ROOT / str(result.run_id)

        payload = json.loads(
            (run_dir / f"{execution.execution_id}.json").read_text()
        )
        assert payload["run_id"] == str(result.run_id)
        assert payload["execution_id"] == str(execution.execution_id)
        assert "otel_trace_id" not in payload
        assert "spans" not in payload
        assert (
            payload["trace"]["name"] == "test.test_module::test_default_trace"
        )
        assert [child["name"] for child in payload["trace"]["children"]] == [
            "default_step"
        ]
        assert payload["trace"]["children"][0]["children"] == []

    @pytest.mark.asyncio
    async def test_otel_reporter_writes_nested_trace_tree(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        async def traced():
            with otel_runtime.start_as_current_span("sut.pipeline.__call__"):
                with otel_runtime.start_as_current_span("first_child"):
                    await asyncio.sleep(0)
                with otel_runtime.start_as_current_span("second_child"):
                    await asyncio.sleep(0)

        monkeypatch.chdir(tmp_path)
        result = await Runner(
            config=make_runner_config(otel=True, db_enabled=False),
            reporters=[OtelReporter()],
        ).run(
            items=[make_item(traced, name="test_nested_trace", is_async=True)]
        )

        execution = result.result.executions[0]
        run_dir = tmp_path / DEFAULT_OTEL_OUTPUT_ROOT / str(result.run_id)
        payload = json.loads(
            (run_dir / f"{execution.execution_id}.json").read_text()
        )

        trace = payload["trace"]
        assert trace["name"] == "test.test_module::test_nested_trace"
        assert [child["name"] for child in trace["children"]] == [
            "sut.pipeline.__call__"
        ]
        assert [
            child["name"] for child in trace["children"][0]["children"]
        ] == ["first_child", "second_child"]
        assert trace["children"][0]["children"][0]["children"] == []
        assert trace["children"][0]["children"][1]["children"] == []

    @pytest.mark.asyncio
    async def test_otel_session_serialize_stays_flat_for_custom_reporters(
        self,
    ):
        reporter = EventReporter()

        async def traced():
            with otel_runtime.start_as_current_span("flat_step"):
                await asyncio.sleep(0)

        result = await Runner(
            config=make_runner_config(otel=True, db_enabled=False),
            reporters=[reporter],
        ).run(items=[make_item(traced, name="test_flat_trace", is_async=True)])

        execution = result.result.executions[0]
        session = reporter.trace_events[0][1]
        payload = session.serialize()

        assert payload["run_id"] == str(result.run_id)
        assert payload["execution_id"] == str(execution.execution_id)
        assert "trace" not in payload
        assert {span["name"] for span in payload["spans"]} == {
            "flat_step",
            "test.test_module::test_flat_trace",
        }

    @pytest.mark.asyncio
    async def test_otel_reporter_recreates_existing_run_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        async def first_trace():
            with otel_runtime.start_as_current_span("first_step"):
                await asyncio.sleep(0)

        async def second_trace():
            with otel_runtime.start_as_current_span("second_step"):
                await asyncio.sleep(0)

        run_id = UUID("00000000-0000-0000-0000-000000000010")
        monkeypatch.chdir(tmp_path)

        first_run = await Runner(
            config=make_runner_config(otel=True, db_enabled=False),
            reporters=[OtelReporter()],
            run_id=run_id,
        ).run(
            items=[
                make_item(first_trace, name="test_first_trace", is_async=True),
                make_item(
                    second_trace, name="test_second_trace", is_async=True
                ),
            ]
        )

        second_run = await Runner(
            config=make_runner_config(otel=True, db_enabled=False),
            reporters=[OtelReporter()],
            run_id=run_id,
        ).run(
            items=[
                make_item(second_trace, name="test_second_trace", is_async=True)
            ]
        )

        run_dir = tmp_path / DEFAULT_OTEL_OUTPUT_ROOT / str(run_id)
        assert sorted(path.stem for path in run_dir.glob("*.json")) == [
            str(second_run.result.executions[0].execution_id)
        ]
        assert str(first_run.result.executions[0].execution_id) not in {
            path.stem for path in run_dir.glob("*.json")
        }

    @pytest.mark.asyncio
    async def test_otel_reporter_prunes_to_last_five_runs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        async def traced():
            with otel_runtime.start_as_current_span("prune_step"):
                await asyncio.sleep(0)

        monkeypatch.chdir(tmp_path)
        kept_run_ids: list[str] = []
        for _ in range(MAX_STORED_OTEL_RUNS + 2):
            result = await Runner(
                config=make_runner_config(otel=True, db_enabled=False),
                reporters=[OtelReporter()],
            ).run(
                items=[
                    make_item(traced, name="test_prune_trace", is_async=True)
                ]
            )
            kept_run_ids.append(str(result.run_id))

        trace_root = tmp_path / DEFAULT_OTEL_OUTPUT_ROOT
        assert sorted(
            path.name for path in trace_root.iterdir() if path.is_dir()
        ) == sorted(kept_run_ids[-MAX_STORED_OTEL_RUNS:])


class TestMaxfail:
    """Tests for maxfail functionality."""

    @pytest.mark.asyncio
    async def test_stops_after_maxfail(self, null_reporter):
        fail_count = 0

        def failing():
            nonlocal fail_count
            fail_count += 1
            assert False

        items = [make_item(failing, name=f"fail_{i}") for i in range(5)]
        runner = Runner(
            config=make_runner_config(maxfail=2),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        assert result.result.failed == 2
        assert result.result.stopped_early
        assert fail_count == 2

    @pytest.mark.asyncio
    async def test_maxfail_counts_errors_too(self, null_reporter):
        def error_test():
            raise RuntimeError

        items = [make_item(error_test, name=f"err_{i}") for i in range(5)]
        runner = Runner(
            config=make_runner_config(maxfail=1),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        assert result.result.errors == 1
        assert result.result.stopped_early


class TestConcurrency:
    """Tests for concurrent test execution."""

    @staticmethod
    def _make_params_item(
        *,
        name: str,
        parameter_sets: tuple[ParameterSet, ...],
    ) -> LoadedTestDef:
        async def params_case(delay: float) -> None:
            await asyncio.sleep(delay)

        return make_definition(
            name,
            fn=params_case,
            is_async=True,
            params=["delay"],
            modifiers=[
                ParamsIterateModifier(
                    parameter_sets=parameter_sets,
                    min_passes=len(parameter_sets),
                )
            ],
        )

    @pytest.mark.asyncio
    async def test_concurrent_execution(self, null_reporter):
        start_times = []

        async def slow_test():
            start_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.1)

        items = [
            make_item(slow_test, name=f"slow_{i}", is_async=True)
            for i in range(3)
        ]
        runner = Runner(
            config=make_runner_config(concurrency=3),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        assert result.result.passed == 3
        # All should start within a small window (concurrent)
        assert max(start_times) - min(start_times) < 0.05

    @pytest.mark.asyncio
    async def test_concurrent_callbacks_stream_before_run_complete(self):
        items = []
        delays = [0.25, 0.05, 0.1]
        for idx, delay in enumerate(delays):

            async def test_fn(d=delay):
                await asyncio.sleep(d)

            items.append(make_item(test_fn, name=f"test_{idx}", is_async=True))

        reporter = EventReporter()
        runner = Runner(
            config=make_runner_config(concurrency=3, db_enabled=False),
            reporters=[reporter],
        )
        await runner.run(items=items)

        complete_times = [
            elapsed
            for kind, _name, elapsed in reporter.event_times
            if kind == "complete"
        ]
        assert complete_times
        assert min(complete_times) < 0.15
        assert min(complete_times) < reporter.run_complete_elapsed

    @pytest.mark.asyncio
    async def test_on_test_start_precedes_on_test_complete_per_item(self):
        items = []
        delays = [0.05, 0.1, 0.02]
        for idx, delay in enumerate(delays):

            async def test_fn(d=delay):
                await asyncio.sleep(d)

            items.append(make_item(test_fn, name=f"test_{idx}", is_async=True))

        reporter = EventReporter()
        runner = Runner(
            config=make_runner_config(concurrency=3, db_enabled=False),
            reporters=[reporter],
        )
        await runner.run(items=items)

        started = {
            name for kind, name in reporter.event_order if kind == "start"
        }
        completed = {
            name for kind, name in reporter.event_order if kind == "complete"
        }
        assert started == completed == {item.spec.name for item in items}

        for item in items:
            start_idx = reporter.event_order.index(("start", item.spec.name))
            complete_idx = reporter.event_order.index(
                ("complete", item.spec.name)
            )
            assert start_idx < complete_idx

    @pytest.mark.asyncio
    async def test_concurrent_raises_when_on_test_start_fails(self):
        async def test_fn():
            await asyncio.sleep(0.01)

        class StartFailureReporter(EventReporter):
            async def on_test_start(self, item: LoadedTestDef) -> None:
                raise RuntimeError("start callback failed")

        runner = Runner(
            config=make_runner_config(concurrency=2, db_enabled=False),
            reporters=[StartFailureReporter()],
        )
        with pytest.raises(RuntimeError, match="start callback failed"):
            await runner.run(
                items=[make_item(test_fn, name="test_start", is_async=True)]
            )

    @pytest.mark.asyncio
    async def test_concurrent_raises_when_on_test_complete_fails(self):
        async def test_fn():
            await asyncio.sleep(0.01)

        class CompleteFailureReporter(EventReporter):
            async def on_execution_complete(
                self, execution: ExecutedTest
            ) -> None:
                raise RuntimeError("complete callback failed")

        runner = Runner(
            config=make_runner_config(concurrency=2, db_enabled=False),
            reporters=[CompleteFailureReporter()],
        )
        with pytest.raises(RuntimeError, match="complete callback failed"):
            await runner.run(
                items=[make_item(test_fn, name="test_complete", is_async=True)]
            )

    @pytest.mark.asyncio
    async def test_subtest_callbacks_stream_before_parent_completion(self):
        item = self._make_params_item(
            name="test_params",
            parameter_sets=(
                ParameterSet(values={"delay": 0.2}, suffix="slow"),
                ParameterSet(values={"delay": 0.01}, suffix="fast"),
                ParameterSet(values={"delay": 0.05}, suffix="mid"),
            ),
        )

        reporter = EventReporter()
        runner = Runner(
            config=make_runner_config(concurrency=3, db_enabled=False),
            reporters=[reporter],
        )
        test_run = await runner.run(items=[item])

        assert len(reporter.subtest_event_times) == 3
        parent_complete_elapsed = next(
            elapsed
            for kind, name, elapsed in reporter.event_times
            if kind == "complete" and name == item.spec.name
        )
        assert max(
            elapsed
            for _parent, _suffix, elapsed in reporter.subtest_event_times
        ) <= (parent_complete_elapsed)
        execution = test_run.result.executions[0]
        assert [
            sub.definition.spec.suffix for sub in execution.sub_executions
        ] == [
            "slow",
            "fast",
            "mid",
        ]

    @pytest.mark.asyncio
    async def test_sequential_execution(self, null_reporter):
        execution_order = []

        async def ordered_test(idx):
            execution_order.append(idx)
            await asyncio.sleep(0.01)

        items = []
        for i in range(3):

            async def test_fn(i=i):
                execution_order.append(i)
                await asyncio.sleep(0.01)

            items.append(make_item(test_fn, name=f"test_{i}", is_async=True))

        runner = Runner(
            config=make_runner_config(concurrency=1),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        assert result.result.passed == 3
        # Should execute in order
        assert execution_order == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_concurrency_zero_caps_at_default(self, null_reporter):
        runner = Runner(
            config=make_runner_config(concurrency=0),
            reporters=[null_reporter],
        )
        assert runner._concurrency_limit() == Runner.DEFAULT_MAX_CONCURRENCY

    @pytest.mark.asyncio
    async def test_concurrent_maxfail(self, null_reporter):
        fail_count = 0

        async def failing():
            nonlocal fail_count
            fail_count += 1
            await asyncio.sleep(0.01)
            assert False

        items = [
            make_item(failing, name=f"fail_{i}", is_async=True)
            for i in range(10)
        ]
        runner = Runner(
            config=make_runner_config(concurrency=5, maxfail=2),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        assert result.result.stopped_early
        # May have more than 2 due to concurrent execution, but should stop
        assert result.result.failed >= 2


class TestTimeout:
    """Tests for run-level timeout."""

    @pytest.mark.asyncio
    async def test_timeout_stops_new_starts(self, null_reporter):
        async def slow_test():
            await asyncio.sleep(0.1)

        async def quick_test():
            await asyncio.sleep(0.01)

        items = [
            make_item(quick_test, name="quick", is_async=True),
            make_item(slow_test, name="slow", is_async=True),
        ]
        runner = Runner(
            config=make_runner_config(concurrency=1, timeout=0.05),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        assert result.result.stopped_early
        assert result.result.passed == 1
        assert result.result.skipped == 0
        assert result.result.total == 1

    @pytest.mark.asyncio
    async def test_no_timeout_by_default(self, null_reporter):
        async def quick_test():
            await asyncio.sleep(0.01)

        item = make_item(quick_test, is_async=True)
        runner = Runner(
            config=make_runner_config(concurrency=2),
            reporters=[null_reporter],
        )
        # timeout is None by default
        assert runner.config.timeout is None

        result = await runner.run(items=[item])
        assert result.result.passed == 1


class TestResultOrdering:
    """Tests for result ordering in concurrent execution."""

    @pytest.mark.asyncio
    async def test_results_ordered_by_discovery(self, null_reporter):
        async def varying_speed(delay):
            await asyncio.sleep(delay)

        items = []
        delays = [0.05, 0.01, 0.03]  # Different completion order
        for i, delay in enumerate(delays):

            async def test_fn(d=delay):
                await asyncio.sleep(d)

            items.append(make_item(test_fn, name=f"test_{i}", is_async=True))

        runner = Runner(
            config=make_runner_config(concurrency=3),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        # Results should be in discovery order, not completion order
        names = [r.definition.spec.name for r in result.result.executions]
        assert names == ["test_0", "test_1", "test_2"]


class TestResourceTeardown:
    """Tests for resource teardown during test runs."""

    @pytest.mark.asyncio
    async def test_case_resources_torn_down_between_tests(self, null_reporter):
        teardown_count = 0

        @resource(scope="test")
        def case_res():
            yield "value"
            nonlocal teardown_count
            teardown_count += 1

        def test_with_case(case_res):
            assert case_res == "value"

        items = [
            make_item(test_with_case, name="test_1", params=["case_res"]),
            make_item(test_with_case, name="test_2", params=["case_res"]),
        ]

        runner = Runner(reporters=[null_reporter])
        result = await runner.run(items=items)

        assert result.result.passed == 2
        assert teardown_count == 2

    @pytest.mark.asyncio
    async def test_suite_resources_shared(self, null_reporter):
        create_count = 0

        @resource(scope="module")
        def suite_res():
            nonlocal create_count
            create_count += 1
            return f"suite_{create_count}"

        captured = []

        def test_suite(suite_res):
            captured.append(suite_res)

        items = [
            make_item(test_suite, name="test_1", params=["suite_res"]),
            make_item(test_suite, name="test_2", params=["suite_res"]),
        ]

        runner = Runner(reporters=[null_reporter])
        await runner.run(items=items)

        assert create_count == 1
        assert captured == ["suite_1", "suite_1"]

    @pytest.mark.asyncio
    async def test_session_resource_created_once_under_concurrency(
        self, null_reporter
    ):
        create_count = 0
        teardown_count = 0

        @resource(scope="process")
        async def session_res():
            nonlocal create_count, teardown_count
            create_count += 1
            await asyncio.sleep(0.02)
            yield f"session_{create_count}"
            teardown_count += 1

        async def test_with_session(session_res):
            assert session_res == "session_1"

        items = [
            make_item(
                test_with_session,
                name=f"test_{i}",
                is_async=True,
                params=["session_res"],
            )
            for i in range(8)
        ]

        runner = Runner(
            config=make_runner_config(concurrency=4),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        assert result.result.passed == len(items)
        assert create_count == 1
        assert teardown_count == 1


class TestResourceResolutionErrors:
    """Tests to ensure resource resolution errors are properly surfaced through the runner."""

    @pytest.mark.asyncio
    async def test_unknown_resource_param_causes_error(self, null_reporter):
        """Test that an unknown resource parameter results in an error."""

        def test_with_unknown(unknown_resource):
            pass

        item = make_item(test_with_unknown, params=["unknown_resource"])
        runner = Runner(reporters=[null_reporter])
        result = await runner.run(items=[item])

        assert result.result.errors == 1
        error = result.result.executions[0].result.error
        assert error is not None
        assert "Unknown resource" in str(error) or "unknown_resource" in str(
            error
        )

    @pytest.mark.asyncio
    async def test_resource_teardown_error_does_not_mask_test_error(
        self, null_reporter
    ):
        """Test that resource teardown errors are surfaced but don't mask test errors."""

        @resource
        def resource_with_teardown_error():
            yield "value"
            raise RuntimeError("Teardown failed")

        def test_that_fails(resource_with_teardown_error):
            assert False, "Test assertion failed"

        item = make_item(
            test_that_fails, params=["resource_with_teardown_error"]
        )
        runner = Runner(reporters=[null_reporter])
        result = await runner.run(items=[item])

        # Test should fail due to assertion, not error
        assert result.result.failed == 1

    @pytest.mark.asyncio
    async def test_resource_resolution_error_in_sequential_mode(
        self, null_reporter
    ):
        """Test that resource resolution errors are surfaced in sequential execution mode."""

        @resource
        def sequential_resource():
            raise RuntimeError("Sequential resource error")

        def test_with_resource(sequential_resource):
            pass

        items = [
            make_item(
                test_with_resource,
                name="test_1",
                params=["sequential_resource"],
            ),
            make_item(lambda: None, name="test_2"),
        ]
        runner = Runner(
            config=make_runner_config(concurrency=1),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        assert result.result.errors == 1
        assert result.result.executions[0].result.error is not None
        assert "Sequential resource error" in str(
            result.result.executions[0].result.error
        )

    @pytest.mark.asyncio
    async def test_resource_resolution_error_in_concurrent_mode(
        self, null_reporter
    ):
        """Test that resource resolution errors are surfaced in concurrent execution mode."""

        @resource
        def concurrent_resource():
            raise RuntimeError("Concurrent resource error")

        def test_with_resource(concurrent_resource):
            pass

        items = [
            make_item(
                test_with_resource,
                name="test_1",
                params=["concurrent_resource"],
            ),
            make_item(lambda: None, name="test_2"),
        ]
        runner = Runner(
            config=make_runner_config(concurrency=2),
            reporters=[null_reporter],
        )
        result = await runner.run(items=items)

        assert result.result.errors == 1
        # Find the errored execution
        errored = [
            e
            for e in result.result.executions
            if e.result.status == TestStatus.ERROR
        ]
        assert len(errored) == 1
        assert "Concurrent resource error" in str(errored[0].result.error)

    @pytest.mark.asyncio
    async def test_suite_scope_resource_error_affects_subsequent_tests(
        self, null_reporter
    ):
        """Test that errors in suite-scope resources affect all subsequent tests."""

        @resource(scope="module")
        def suite_resource():
            raise RuntimeError("Suite resource failed")

        def test_with_suite(suite_resource):
            pass

        items = [
            make_item(
                test_with_suite, name="test_1", params=["suite_resource"]
            ),
            make_item(
                test_with_suite, name="test_2", params=["suite_resource"]
            ),
        ]
        runner = Runner(reporters=[null_reporter])
        result = await runner.run(items=items)

        # Both tests should error due to suite resource failure
        assert result.result.errors == 2
