"""Tests for runner-managed Rue tracing."""

import sys
from pathlib import Path
from uuid import uuid4

import pytest

from rue.testing.discovery import collect
from rue.testing.runner import Runner
from rue.telemetry.otel import otel_span


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


@pytest.mark.asyncio
async def test_otel_trace_injection_and_otel_span_work_inside_runner(
    tmp_path: Path,
    trace_reporter,
    monkeypatch: pytest.MonkeyPatch,
):
    mod_name, run, sessions = await _run_module_with_tracing(
        tmp_path=tmp_path,
        trace_reporter=trace_reporter,
        monkeypatch=monkeypatch,
        source="""
import rue

def test_sample(otel_trace: rue.OtelTrace):
    with rue.otel_span("child_step", {"key": "value"}):
        pass

    child_spans = otel_trace.get_child_spans()
    assert any(span.name == "child_step" for span in child_spans)
    otel_trace.set_attribute("my.custom.attr", "value")
""",
    )

    assert run.result.passed == 1
    payloads = [session.serialize() for session in sessions]
    root_span = next(
        span
        for payload in payloads
        for span in payload["spans"]
        if span["name"] == f"test.{mod_name}::test_sample"
    )
    child_span = next(
        span
        for payload in payloads
        for span in payload["spans"]
        if span["name"] == "child_step"
    )

    assert root_span["attributes"]["my.custom.attr"] == "value"
    assert child_span["attributes"]["key"] == "value"


@pytest.mark.asyncio
async def test_otel_span_is_no_op_outside_runner_even_after_runtime_configured(
    tmp_path: Path,
    trace_reporter,
    monkeypatch: pytest.MonkeyPatch,
):
    _, run, sessions = await _run_module_with_tracing(
        tmp_path=tmp_path,
        trace_reporter=trace_reporter,
        monkeypatch=monkeypatch,
        source="""
import rue

def test_sample():
    with rue.otel_span("inside_step"):
        pass
""",
    )

    assert run.result.passed == 1
    before = [session.serialize() for session in sessions]

    with otel_span("outside_step", {"ignored": True}) as span:
        span.set_attribute("more", "ignored")

    after = [session.serialize() for session in sessions]
    assert before == after
    assert all(
        "outside_step"
        not in {inner_span["name"] for inner_span in content["spans"]}
        for content in after
    )
