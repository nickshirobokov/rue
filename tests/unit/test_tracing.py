"""Tests for suite-managed Rue tracing."""

import sys
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import pytest

from rue.resources import DependencyResolver, registry
from rue.testing.execution.suite.executable import ExecutableSuite
from tests.helpers import make_suite_context, materialize_tests


def _write_temp_module(tmp_path: Path, source: str) -> tuple[str, Path]:
    mod_name = f"test_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(source.lstrip())
    return mod_name, mod_path


def _artifact_payload(artifact) -> dict[str, object]:
    return {
        "suite_execution_id": str(artifact.suite_execution_id),
        "test_execution_id": str(artifact.test_execution_id),
        "spans": artifact.spans,
    }


async def _suite_module_with_tracing(
    *,
    tmp_path: Path,
    trace_processor,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
):
    mod_name, mod_path = _write_temp_module(tmp_path, source)

    try:
        monkeypatch.chdir(tmp_path)
        items = materialize_tests(mod_path)
        context = make_suite_context(
            otel=True,
            processors=(trace_processor,),
        )
        suite = await ExecutableSuite(
            items=items,
            suite_execution_id=context.suite_execution_id,
            resolver=DependencyResolver(registry),
        ).execute()
        return mod_name, suite, trace_processor.artifacts
    finally:
        sys.modules.pop(mod_name, None)


@pytest.mark.parametrize(
    "source",
    [
        """
import rue
from rue.telemetry.otel.runtime import otel_runtime

@rue.predicate
def is_ok(actual: str, reference: str) -> bool:
    return actual == reference

@rue.resource.sut
def traced_pipeline():
    def run() -> str:
        with otel_runtime.start_as_current_span("child_step") as span:
            span.set_attribute("key", "value")
        with otel_runtime.start_as_current_span("openai.responses.create"):
            pass
        assert is_ok("ok", "ok")
        return "ok"

    return rue.SUT(run)

@rue.test
def test_sample(traced_pipeline):
    assert traced_pipeline.root_spans == []
    assert traced_pipeline.all_spans == []
    assert traced_pipeline.llm_spans == []

    assert traced_pipeline.instance() == "ok"
    assert {span.name for span in traced_pipeline.root_spans} == {
        "sut.traced_pipeline.__call__"
    }
    assert {span.name for span in traced_pipeline.all_spans} == {
        "sut.traced_pipeline.__call__",
        "child_step",
        "openai.responses.create",
        "predicate.is_ok",
    }
    assert [span.name for span in traced_pipeline.llm_spans] == [
        "openai.responses.create"
    ]
""",
        """
import rue
from rue.telemetry.otel.runtime import otel_runtime

@rue.predicate
def is_ok(actual: str, reference: str) -> bool:
    return actual == reference

@rue.resource.sut
def traced_pipeline():
    async def run() -> str:
        with otel_runtime.start_as_current_span("child_step") as span:
            span.set_attribute("key", "value")
        with otel_runtime.start_as_current_span("openai.responses.create"):
            pass
        assert is_ok("ok", "ok")
        return "ok"

    return rue.SUT(run)

@rue.test
async def test_sample(traced_pipeline):
    assert traced_pipeline.root_spans == []
    assert traced_pipeline.all_spans == []
    assert traced_pipeline.llm_spans == []

    assert await traced_pipeline.instance() == "ok"
    assert {span.name for span in traced_pipeline.root_spans} == {
        "sut.traced_pipeline.__call__"
    }
    assert {span.name for span in traced_pipeline.all_spans} == {
        "sut.traced_pipeline.__call__",
        "child_step",
        "openai.responses.create",
        "predicate.is_ok",
    }
    assert [span.name for span in traced_pipeline.llm_spans] == [
        "openai.responses.create"
    ]
""",
    ],
)
@pytest.mark.asyncio
async def test_sut_trace_accessors_work_inside_suite(
    tmp_path: Path,
    trace_processor,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
):
    mod_name, suite, artifacts = await _suite_module_with_tracing(
        tmp_path=tmp_path,
        trace_processor=trace_processor,
        monkeypatch=monkeypatch,
        source=source,
    )

    assert suite.result.passed == 1
    payloads = [_artifact_payload(artifact) for artifact in artifacts]
    assert any(
        span["name"] == f"test.{mod_name}::test_sample"
        for payload in payloads
        for span in payload["spans"]
    )
    child_span = next(
        span
        for payload in payloads
        for span in payload["spans"]
        if span["name"] == "child_step"
    )

    assert child_span["attributes"]["key"] == "value"


def test_public_otel_trace_and_otel_span_are_removed():
    rue = import_module("rue")
    rue_telemetry = import_module("rue.telemetry")
    rue_otel = import_module("rue.telemetry.otel")

    assert not hasattr(rue, "OtelTrace")
    assert not hasattr(rue, "OtelTraceSession")
    assert not hasattr(rue, "otel_span")
    assert not hasattr(rue_telemetry, "OtelTraceSession")
    assert not hasattr(rue_otel, "OtelTrace")
    assert not hasattr(rue_otel, "OtelTraceSession")
    assert not hasattr(rue_otel, "otel_span")
