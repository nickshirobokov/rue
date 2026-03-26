"""Tests for runner-managed Rue tracing."""

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from rue.testing.discovery import collect
from rue.testing.runner import Runner
from rue.telemetry.otel import otel_span


def _span_from_output(otel_output_path: Path, name: str) -> dict[str, object]:
    for line in otel_output_path.read_text().splitlines():
        span = json.loads(line)
        if span["name"] == name:
            return span
    raise AssertionError(f"Missing span {name!r}")


def _write_temp_module(tmp_path: Path, source: str) -> tuple[str, Path]:
    mod_name = f"rue_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(source.lstrip())
    return mod_name, mod_path


async def _run_module_with_tracing(
    *,
    tmp_path: Path,
    null_reporter,
    source: str,
    trace_name: str = "test_traces.jsonl",
):
    mod_name, mod_path = _write_temp_module(tmp_path, source)
    trace_path = tmp_path / trace_name

    try:
        items = collect(mod_path)
        run = await Runner(
            reporters=[null_reporter],
            otel_enabled=True,
            otel_output=trace_path,
            db_enabled=False,
        ).run(items=items)
        return mod_name, run, trace_path
    finally:
        sys.modules.pop(mod_name, None)


@pytest.mark.asyncio
async def test_otel_trace_injection_and_otel_span_work_inside_runner(
    tmp_path: Path,
    null_reporter,
):
    mod_name, run, otel_output_path = await _run_module_with_tracing(
        tmp_path=tmp_path,
        null_reporter=null_reporter,
        source="""
import rue

def test_sample(otel_trace: rue.OtelTrace):
    assert otel_trace.is_enabled is True

    with rue.otel_span("child_step", {"key": "value"}):
        pass

    child_spans = otel_trace.get_child_spans()
    assert any(span.name == "child_step" for span in child_spans)
    otel_trace.set_attribute("my.custom.attr", "value")
""",
    )

    assert run.result.passed == 1
    root_span = _span_from_output(otel_output_path, f"test.{mod_name}::test_sample")
    child_span = _span_from_output(otel_output_path, "child_step")

    assert root_span["attributes"]["my.custom.attr"] == "value"
    assert child_span["attributes"]["key"] == "value"


@pytest.mark.asyncio
async def test_otel_span_is_no_op_outside_runner_even_after_runtime_configured(
    tmp_path: Path,
    null_reporter,
):
    _, run, otel_output_path = await _run_module_with_tracing(
        tmp_path=tmp_path,
        null_reporter=null_reporter,
        source="""
import rue

def test_sample():
    with rue.otel_span("inside_step"):
        pass
""",
        trace_name="noop_traces.jsonl",
    )

    assert run.result.passed == 1
    before = otel_output_path.read_text()

    with otel_span("outside_step", {"ignored": True}) as span:
        span.set_attribute("more", "ignored")

    after = otel_output_path.read_text()
    assert before == after
    assert "outside_step" not in after
