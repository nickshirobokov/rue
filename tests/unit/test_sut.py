"""Tests for rue.testing.sut module."""

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic_core import ValidationError

from rue import SUT
from rue.config import RueConfig
from rue.resources import ResourceResolver, registry as resources_registry
from rue.testing.discovery import collect
from rue.testing.models import Case
from rue.testing.runner import Runner
from rue.testing.sut import sut


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
            config=RueConfig.model_construct(otel=True, db_enabled=False),
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
    def test_calls_callable(self):
        def run(x: int, y: int) -> int:
            return x + y

        target = SUT(run)

        assert target(2, 3) == 5
        assert target.name == "run"

    def test_uses_call_for_callable_objects(self):
        class Pipeline:
            def __call__(self, value: int) -> int:
                return value * 4

        target = SUT(Pipeline())

        assert target(3) == 12

    def test_allows_bound_methods(self):
        class Service:
            def run(self, value: str) -> str:
                return f"ok:{value}"

        target = SUT(Service().run)

        assert target("hello") == "ok:hello"
        assert target.name == "run"

    @pytest.mark.asyncio
    async def test_calls_async_method(self):
        class Service:
            async def run(self, value: str) -> str:
                return f"ok:{value}"

        target = SUT(Service(), method="run")

        assert await target("hello") == "ok:hello"

    def test_explicit_name_wins(self):
        def run(value: int) -> int:
            return value * 2

        target = SUT(run, name="custom")

        assert target.name == "custom"

    def test_validates_cases_in_init(self):
        class Pipeline:
            def run(self, x: int) -> int:
                return x * 2

        target = SUT(
            Pipeline(),
            method="run",
            validate_cases=[Case(inputs={"x": 7})],
        )

        assert target(3) == 6
        assert target.args_schema is not None
        assert target.validator is not None

    def test_validation_raises_on_invalid_case(self):
        class Pipeline:
            def run(self, x: int) -> int:
                return x * 2

        with pytest.raises(ValidationError):
            SUT(
                Pipeline(),
                method="run",
                validate_cases=[Case(inputs={"x": "bad"})],
            )

    @pytest.mark.parametrize(
        "method, expected_match",
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
            SUT(Service(), method=method)


class TestSutDecorator:
    def test_rejects_classes(self):
        with pytest.raises(TypeError, match="only decorate functions"):
            sut(type("MySUT", (), {}))

    @pytest.mark.parametrize(
        "kwargs",
        [{"method": "run"}, {"validate_cases": [Case(inputs={"x": 1})]}],
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
            return SUT(Pipeline(), method="run")

        resolved = await _resolve("pipeline")

        assert isinstance(resolved, SUT)
        assert resolved.name == "pipeline"
        assert resolved(3) == 6


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
    return rue.SUT(run)

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
    async def run(self, value: str) -> str:
        return f"ok:{value}"

@rue.sut
def traced_service():
    return rue.SUT(Service(), method="run")

async def test_sample(traced_service):
    assert await traced_service("hello") == "ok:hello"
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

        assert target(2, 3) == 5

        after = [session.serialize() for session in sessions]
        assert before == after
