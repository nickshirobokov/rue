"""Tests for rue.resources.sut module."""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import assert_type
from uuid import uuid4

import pytest
from pydantic_core import ValidationError

from rue import SUT
from rue.config import Config
from rue.resources import ResourceResolver, registry as resources_registry
from rue.resources.sut import sut
from rue.resources.sut.output import SUTOutputCapture
from rue.testing.discovery import collect
from rue.testing.models import Case
from rue.testing.runner import Runner


@pytest.fixture(autouse=True)
def clean_registry():
    resources_registry.reset()
    yield
    resources_registry.reset()


def _write_temp_module(tmp_path: Path, source: str) -> tuple[str, Path]:
    mod_name = f"rue_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(source.lstrip())
    return mod_name, mod_path


async def _run_module_with_tracing(
    *,
    tmp_path: Path,
    trace_reporter,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
):
    mod_name, mod_path = _write_temp_module(tmp_path, source)

    try:
        monkeypatch.chdir(tmp_path)
        items = collect(mod_path)
        runner = Runner(
            config=Config.model_construct(otel=True, db_enabled=False),
            reporters=[trace_reporter],
        )
        run = await runner.run(items=items)
        return mod_name, run, trace_reporter.sessions
    finally:
        sys.modules.pop(mod_name, None)


async def _resolve(name: str) -> object:
    resolver = ResourceResolver(resources_registry)
    return await resolver.resolve(name)


class TestSutObject:
    def test_preserves_callable_type_for_type_checking(self) -> None:
        def run(x: int, y: int) -> int:
            return x + y

        target: SUT[Callable[[int, int], int]] = SUT(run)

        assert_type(target.instance, Callable[[int, int], int])
        assert target.instance(2, 3) == 5

    def test_calls_callable(self):
        def run(x: int, y: int) -> int:
            return x + y

        target = SUT(run)

        assert target.instance(2, 3) == 5
        assert not callable(target)
        assert target.name == "run"

    def test_uses_call_for_callable_objects(self) -> None:
        class Pipeline:
            def __call__(self, value: int) -> int:
                return value * 4

        target: SUT[Pipeline] = SUT(Pipeline())

        assert_type(target.instance, Pipeline)
        assert target.instance(3) == 12

    def test_allows_bound_methods(self):
        class Service:
            def run(self, value: str) -> str:
                return f"ok:{value}"

        target = SUT(Service().run)

        assert target.instance("hello") == "ok:hello"
        assert target.name == "run"

    @pytest.mark.asyncio
    async def test_wraps_sync_and_async_methods(self):
        class Service:
            async def run(self, value: str) -> str:
                return f"ok:{value}"

            def predict(self, value: int) -> int:
                return value * 2

        target = SUT(Service(), methods=["run", "predict"])

        assert await target.instance.run("hello") == "ok:hello"
        assert target.instance.predict(3) == 6

    def test_captures_stdout_stderr_and_event_order(self):
        def run() -> str:
            sys.stdout.write("out-1")
            sys.stderr.write("err-1")
            sys.stdout.write("out-2")
            return "ok"

        target = SUT(run)

        assert target.instance() == "ok"
        assert target.stdout.text == "out-1out-2"
        assert target.stderr.text == "err-1"
        assert target.captured_output.combined.text == "out-1err-1out-2"
        assert [
            (event.stream, event.text) for event in target.captured_output.events
        ] == [
            ("stdout", "out-1"),
            ("stderr", "err-1"),
            ("stdout", "out-2"),
        ]

    def test_appends_output_across_multiple_calls(self):
        def run(value: str) -> str:
            print(value)
            return value

        target = SUT(run)

        assert target.instance("first") == "first"
        assert target.instance("second") == "second"
        assert target.stdout.text == "first\nsecond\n"
        assert target.stdout.lines == ("first", "second")

    def test_clear_output_resets_current_context_state(self):
        def run() -> None:
            print("hello")

        target = SUT(run)

        target.instance()
        assert target.stdout.text == "hello\n"

        target.clear_output()

        assert target.stdout.text == ""
        assert target.stderr.text == ""
        assert target.captured_output.events == ()

    def test_wraps_instance_methods_with_output_capture(self):
        class Service:
            def run(self) -> None:
                print("run")

            def predict(self) -> None:
                sys.stderr.write("predict\n")

        target = SUT(Service(), methods=["run", "predict"])

        target.instance.run()
        target.instance.predict()

        assert target.stdout.text == "run\n"
        assert target.stderr.text == "predict\n"

    def test_nested_sut_calls_duplicate_output_into_parent_and_child(self):
        def run_child() -> None:
            sys.stdout.write("child|")

        child = SUT(run_child, name="child")

        def run_parent() -> None:
            sys.stdout.write("parent|")
            child.instance()
            sys.stderr.write("done|")

        parent = SUT(run_parent, name="parent")

        parent.instance()

        assert child.captured_output.combined.text == "child|"
        assert parent.captured_output.combined.text == "parent|child|done|"
        assert parent.stdout.text == "parent|child|"
        assert parent.stderr.text == "done|"

    def test_lazy_installs_and_uninstalls_sys_capture_outside_runner(self):
        def run() -> None:
            print("hello")

        target = SUT(run)

        assert not SUTOutputCapture.is_sys_capture_installed()
        target.instance()
        assert not SUTOutputCapture.is_sys_capture_installed()
        assert target.stdout.text == "hello\n"

    def test_explicit_name_wins(self):
        def run(value: int) -> int:
            return value * 2

        target = SUT(run, name="custom")

        assert target.name == "custom"

    def test_validates_cases_for_selected_method(self):
        class Pipeline:
            def run(self, x: int) -> int:
                return x * 2

        target = SUT(Pipeline(), methods=["run"])
        target.validate_cases([Case(inputs={"x": 7})], "run")

        assert target.instance.run(3) == 6

    def test_validation_raises_on_invalid_case(self):
        class Pipeline:
            def run(self, x: int) -> int:
                return x * 2

        target = SUT(Pipeline(), methods=["run"])

        with pytest.raises(ValidationError):
            target.validate_cases([Case(inputs={"x": "bad"})], "run")

    def test_validation_raises_on_unknown_method(self):
        def run(x: int) -> int:
            return x * 2

        target = SUT(run)

        with pytest.raises(ValueError, match="Method 'run' not found in SUT"):
            target.validate_cases([Case(inputs={"x": 1})], "run")

    @pytest.mark.parametrize(
        ("method", "expected_match"),
        [
            ("run", r"Method 'run' not found"),
            ("value", r"Method 'value' is not a callable"),
        ],
    )
    def test_rejects_missing_and_non_callable_methods(
        self, method: str, expected_match: str
    ):
        class Service:
            value = 1

        with pytest.raises(ValueError, match=expected_match):
            SUT(Service(), methods=[method])


class TestSutDecorator:
    def test_rejects_classes(self):
        with pytest.raises(TypeError, match="only decorate functions"):
            sut(type("MySUT", (), {}))

    @pytest.mark.parametrize(
        "kwargs",
        [{"methods": ["run"]}, {"validate_cases": [Case(inputs={"x": 1})]}],
    )
    def test_removed_decorator_kwargs_raise(self, kwargs):
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            sut(**kwargs)

    @pytest.mark.asyncio
    async def test_requires_explicit_sut_return(self):
        @sut
        def bad_sut():
            return lambda x: x + 1

        with pytest.raises(
            RuntimeError, match="@sut factories must return or yield a SUT"
        ) as exc:
            await _resolve("bad_sut")

        assert isinstance(exc.value.__cause__, TypeError)

    @pytest.mark.asyncio
    async def test_sets_name_from_factory(self):
        class Pipeline:
            def run(self, x: int) -> int:
                return x * 2

        @sut
        def pipeline():
            return SUT(Pipeline(), methods=["run"])

        resolved = await _resolve("pipeline")

        assert isinstance(resolved, SUT)
        assert resolved.name == "pipeline"
        assert resolved.instance.run(3) == 6


class TestSutOpenTelemetry:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("source", "span_name", "expected_attrs"),
        [
            (
                """
import rue

@rue.resource.sut
def traced_sut():
    def run(x: int) -> int:
        return x * 2
    return rue.SUT(run)

def test_sample(traced_sut):
    assert traced_sut.instance(5) == 10
""",
                "sut.traced_sut.__call__",
                {
                    "rue.sut": True,
                    "rue.sut.name": "traced_sut",
                    "rue.sut.method": "__call__",
                },
            ),
            (
                """
import rue

class Pipeline:
    def __call__(self, value: int) -> int:
        return value * 4

@rue.resource.sut
def traced_callable_object():
    return rue.SUT(Pipeline())

def test_sample(traced_callable_object):
    assert traced_callable_object.instance(3) == 12
""",
                "sut.traced_callable_object.__call__",
                {
                    "rue.sut": True,
                    "rue.sut.name": "traced_callable_object",
                    "rue.sut.method": "__call__",
                },
            ),
            (
                """
import rue

class Service:
    async def run(self, value: str) -> str:
        return f"ok:{value}"

@rue.resource.sut
def traced_service():
    return rue.SUT(Service(), methods=["run"])

async def test_sample(traced_service):
    assert await traced_service.instance.run("hello") == "ok:hello"
""",
                "sut.traced_service.run",
                {
                    "rue.sut": True,
                    "rue.sut.name": "traced_service",
                    "rue.sut.method": "run",
                },
            ),
        ],
    )
    async def test_sut_creates_span(
        self,
        tmp_path: Path,
        trace_reporter,
        monkeypatch: pytest.MonkeyPatch,
        source: str,
        span_name: str,
        expected_attrs: dict[str, object],
    ):
        mod_name, run, sessions = await _run_module_with_tracing(
            tmp_path=tmp_path,
            trace_reporter=trace_reporter,
            monkeypatch=monkeypatch,
            source=source,
        )

        assert run.result.passed == 1
        payloads = [session.serialize() for session in sessions]
        span = next(
            span
            for payload in payloads
            for span in payload["spans"]
            if span["name"] == span_name
        )
        assert f"test.{mod_name}::test_sample" in {
            inner_span["name"]
            for payload in payloads
            for inner_span in payload["spans"]
        }
        for key, value in expected_attrs.items():
            assert span["attributes"].get(key) == value

    @pytest.mark.asyncio
    async def test_sut_does_not_trace_outside_runner_even_after_runtime_configured(
        self,
        tmp_path: Path,
        trace_reporter,
        monkeypatch: pytest.MonkeyPatch,
    ):
        _, _, sessions = await _run_module_with_tracing(
            tmp_path=tmp_path,
            trace_reporter=trace_reporter,
            monkeypatch=monkeypatch,
            source="""
def test_sample():
    assert True
""",
        )

        def run(x: int, y: int) -> int:
            return x + y

        target = SUT(run)
        before = [session.serialize() for session in sessions]

        assert target.instance(2, 3) == 5

        after = [session.serialize() for session in sessions]
        assert before == after

    @pytest.mark.asyncio
    async def test_async_sut_accessors_include_child_and_llm_spans(
        self,
        tmp_path: Path,
        trace_reporter,
        monkeypatch: pytest.MonkeyPatch,
    ):
        _, run, _ = await _run_module_with_tracing(
            tmp_path=tmp_path,
            trace_reporter=trace_reporter,
            monkeypatch=monkeypatch,
            source="""
import rue
from rue.telemetry.otel.runtime import otel_runtime

@rue.resource.sut
def traced_pipeline():
    async def run() -> str:
        with otel_runtime.start_as_current_span("child_step"):
            pass
        with otel_runtime.start_as_current_span("openai.responses.create"):
            pass
        return "ok"

    return rue.SUT(run)

async def test_sample(traced_pipeline):
    assert traced_pipeline.root_spans == []
    assert traced_pipeline.all_spans == []
    assert traced_pipeline.llm_spans == []
    assert traced_pipeline.stdout.text == ""

    assert await traced_pipeline.instance() == "ok"
    assert {span.name for span in traced_pipeline.root_spans} == {
        "sut.traced_pipeline.__call__"
    }
    assert {span.name for span in traced_pipeline.all_spans} == {
        "sut.traced_pipeline.__call__",
        "child_step",
        "openai.responses.create",
    }
    assert [span.name for span in traced_pipeline.llm_spans] == [
        "openai.responses.create"
    ]
""",
        )

        assert run.result.passed == 1

    @pytest.mark.parametrize("scope", ["suite", "session"])
    @pytest.mark.parametrize("concurrency", [1, 2])
    @pytest.mark.asyncio
    async def test_shared_scope_sut_trace_state_stays_isolated(
        self,
        tmp_path: Path,
        trace_reporter,
        monkeypatch: pytest.MonkeyPatch,
        scope: str,
        concurrency: int,
    ):
        _ = concurrency
        _, run, _ = await _run_module_with_tracing(
            tmp_path=tmp_path,
            trace_reporter=trace_reporter,
            monkeypatch=monkeypatch,
            source=f"""
import asyncio

import rue
from rue.telemetry.otel.runtime import otel_runtime

@rue.resource.sut(scope="{scope}")
def shared_pipeline():
    async def run(step: str) -> str:
        print(step)
        with otel_runtime.start_as_current_span(step):
            await asyncio.sleep(0.01)
        return step

    return rue.SUT(run)

async def test_first(shared_pipeline):
    assert shared_pipeline.all_spans == []
    assert shared_pipeline.stdout.text == ""
    assert await shared_pipeline.instance("first_step") == "first_step"
    assert shared_pipeline.stdout.text == "first_step\\n"
    assert {{span.name for span in shared_pipeline.all_spans}} == {{
        "sut.shared_pipeline.__call__",
        "first_step",
    }}

async def test_second(shared_pipeline):
    assert shared_pipeline.all_spans == []
    assert shared_pipeline.stdout.text == ""
    assert await shared_pipeline.instance("second_step") == "second_step"
    assert shared_pipeline.stdout.text == "second_step\\n"
    assert {{span.name for span in shared_pipeline.all_spans}} == {{
        "sut.shared_pipeline.__call__",
        "second_step",
    }}
""",
        )

        assert run.result.passed == 2
