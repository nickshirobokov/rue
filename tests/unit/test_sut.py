"""Tests for rue.testing.sut module."""

import asyncio
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel
from pydantic_core import ValidationError

from rue.resources import ResourceResolver, Scope, clear_registry, get_registry, resource
from rue.testing.discovery import collect
from rue.testing.models import Case
from rue.testing.runner import Runner
from rue.testing.sut import sut


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


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
            reporters=[trace_reporter],
            otel_enabled=True,
            db_enabled=False,
        )
        run = await runner.run(items=items)
        return mod_name, run, trace_reporter.sessions
    finally:
        sys.modules.pop(mod_name, None)


class TestSutDecorator:
    def test_rejects_classes(self):
        with pytest.raises(TypeError, match="only decorate functions"):
            sut(type("MySUT", (), {}))

    def test_registers_resource_with_case_scope_by_default(self):
        @sut
        def my_sut():
            return lambda x: x * 2

        registry = get_registry()
        assert "my_sut" in registry
        assert registry["my_sut"].scope == Scope.CASE

    def test_scope_is_user_defined(self):
        @sut(scope=Scope.SESSION)
        def my_session_sut():
            return lambda x: x

        registry = get_registry()
        assert registry["my_session_sut"].scope == Scope.SESSION

    def test_resource_dependencies_are_captured_from_factory_signature(self):
        @resource
        def dep():
            return 3

        @sut
        def my_sut(dep):
            return lambda x: x + dep

        registry = get_registry()
        assert registry["my_sut"].dependencies == ["dep"]

    def test_registry_key_is_factory_function_name(self):
        @sut
        def original_name():
            return lambda: "ok"

        registry = get_registry()
        assert "original_name" in registry


class TestSutResolution:
    @pytest.mark.asyncio
    async def test_wraps_returned_callable(self):
        @sut
        def adder():
            def run(x: int, y: int) -> int:
                return x + y

            return run

        resolver = ResourceResolver(get_registry())
        resolved = await resolver.resolve("adder")

        assert callable(resolved)
        assert resolved(2, 3) == 5
        assert inspect.signature(resolved) == inspect.signature(adder())

    @pytest.mark.asyncio
    async def test_wraps_returned_async_callable(self):
        @sut
        def async_adder():
            async def run(x: int, y: int) -> int:
                await asyncio.sleep(0.001)
                return x + y

            return run

        resolver = ResourceResolver(get_registry())
        resolved = await resolver.resolve("async_adder")
        assert await resolved(2, 3) == 5

    @pytest.mark.asyncio
    async def test_wraps_returned_instance_method_in_place(self):
        class Pipeline:
            def __init__(self) -> None:
                self.factor = 4

            def run(self, x: int) -> int:
                return x * self.factor

        @sut(method="run")
        def pipeline():
            return Pipeline()

        resolver = ResourceResolver(get_registry())
        resolved = await resolver.resolve("pipeline")

        assert isinstance(resolved, Pipeline)
        assert resolved.factor == 4
        assert resolved.run(3) == 12

    @pytest.mark.asyncio
    async def test_raises_on_none_return(self):
        @sut
        def bad_sut():
            return None

        resolver = ResourceResolver(get_registry())
        with pytest.raises(RuntimeError, match="Hook on_resolve failed"):
            await resolver.resolve("bad_sut")

    @pytest.mark.asyncio
    async def test_raises_when_method_missing_for_non_callable_instance(self):
        class NoRun:
            value = 1

        @sut(method="run")
        def no_run():
            return NoRun()

        resolver = ResourceResolver(get_registry())
        with pytest.raises(RuntimeError, match="resolved to unsupported type"):
            await resolver.resolve("no_run")

    @pytest.mark.asyncio
    async def test_validate_cases_applies_to_resolved_callable_signature(self):
        cases = [Case(inputs={"x": 1, "y": 2})]

        @sut(validate_cases=cases)
        def adder():
            def run(x: int, y: int) -> int:
                return x + y

            return run

        resolver = ResourceResolver(get_registry())
        resolved = await resolver.resolve("adder")

        assert resolved(2, 3) == 5

    @pytest.mark.asyncio
    async def test_validate_cases_applies_to_typed_inputs(self):
        class AdderInputs(BaseModel):
            x: int
            y: int

        cases = [
            Case[AdderInputs, dict[str, int]](inputs=AdderInputs(x=1, y=2)),
        ]

        @sut(validate_cases=cases)
        def adder():
            def run(x: int, y: int) -> int:
                return x + y

            return run

        resolver = ResourceResolver(get_registry())
        resolved = await resolver.resolve("adder")

        assert resolved(**cases[0].inputs.model_dump()) == 3

    @pytest.mark.asyncio
    async def test_validate_cases_applies_to_dataclass_inputs(self):
        @dataclass
        class AdderInputs:
            x: int
            y: int

        cases = [Case[AdderInputs, dict[str, int]](inputs=AdderInputs(x=1, y=2))]

        @sut(validate_cases=cases)
        def adder():
            def run(x: int, y: int) -> int:
                return x + y

            return run

        resolver = ResourceResolver(get_registry())
        resolved = await resolver.resolve("adder")

        assert resolved(x=cases[0].inputs.x, y=cases[0].inputs.y) == 3

    @pytest.mark.asyncio
    async def test_validate_cases_raises_on_invalid_case(self):
        cases = [Case(inputs={"x": "not-an-int"})]

        @sut(validate_cases=cases)
        def increment():
            def run(x: int) -> int:
                return x + 1

            return run

        resolver = ResourceResolver(get_registry())
        with pytest.raises(RuntimeError, match="Hook on_resolve failed") as exc:
            await resolver.resolve("increment")

        assert isinstance(exc.value.__cause__, ValidationError)

    @pytest.mark.asyncio
    async def test_validate_cases_raises_on_invalid_dataclass_case(self):
        @dataclass
        class IncrementInputs:
            x: int

        cases = [
            Case[IncrementInputs, dict[str, int]](inputs=IncrementInputs(x="bad")),
        ]

        @sut(validate_cases=cases)
        def increment():
            def run(x: int) -> int:
                return x + 1

            return run

        resolver = ResourceResolver(get_registry())
        with pytest.raises(RuntimeError, match="Hook on_resolve failed") as exc:
            await resolver.resolve("increment")

        assert isinstance(exc.value.__cause__, ValidationError)

    @pytest.mark.asyncio
    async def test_validate_cases_raises_on_invalid_typed_case(self):
        class IncrementInputs(BaseModel):
            x: str

        cases = [Case[IncrementInputs, dict[str, int]](inputs=IncrementInputs(x="not-an-int"))]

        @sut(validate_cases=cases)
        def increment():
            def run(x: int) -> int:
                return x + 1

            return run

        resolver = ResourceResolver(get_registry())
        with pytest.raises(RuntimeError, match="Hook on_resolve failed") as exc:
            await resolver.resolve("increment")

        assert isinstance(exc.value.__cause__, ValidationError)

    @pytest.mark.asyncio
    async def test_validate_cases_targets_instance_method_signature(self):
        class Pipeline:
            def run(self, x: int) -> int:
                return x * 2

        cases = [Case(inputs={"x": 7})]

        @sut(method="run", validate_cases=cases)
        def pipeline():
            return Pipeline()

        resolver = ResourceResolver(get_registry())
        resolved = await resolver.resolve("pipeline")

        assert resolved.run(3) == 6


class TestSutOpenTelemetry:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("source", "span_name", "expected_attrs"),
        [
            (
                """
import rue

@rue.sut
def traced_sut():
    def run(x: int) -> int:
        return x * 2
    return run

def test_sample(traced_sut):
    assert traced_sut(5) == 10
""",
                "sut.traced_sut",
                {"rue.sut": True, "rue.sut.name": "traced_sut"},
            ),
            (
                """
import rue

class Service:
    def run(self, value: str) -> str:
        return f"ok:{value}"

@rue.sut(method="run")
def traced_service():
    return Service()

def test_sample(traced_service):
    assert traced_service.run("hello") == "ok:hello"
""",
                "sut.traced_service",
                {"rue.sut": True, "rue.sut.name": "traced_service"},
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
            inner_span["name"] for payload in payloads for inner_span in payload["spans"]
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

        @sut
        def adder():
            def run(x: int, y: int) -> int:
                return x + y

            return run

        resolver = ResourceResolver(get_registry())
        resolved = await resolver.resolve("adder")
        before = [session.serialize() for session in sessions]

        assert resolved(2, 3) == 5

        after = [session.serialize() for session in sessions]
        assert before == after
