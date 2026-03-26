from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from opentelemetry.trace import StatusCode

from rue.testing.models import TestDefinition, TestResult, TestStatus
from rue.testing.tracing import TestTracer


class FakeSpan:
    def __init__(self, *, trace_id: int = 1) -> None:
        self.attributes: dict[str, object] = {}
        self.exceptions: list[Exception] = []
        self.status: tuple[StatusCode, str] | None = None
        self._context = SimpleNamespace(trace_id=trace_id)

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def set_status(self, code: StatusCode, description: str) -> None:
        self.status = (code, description)

    def record_exception(self, error: Exception) -> None:
        self.exceptions.append(error)

    def get_span_context(self):
        return self._context


class FakeSpanScope:
    def __init__(self, span: FakeSpan) -> None:
        self.span = span
        self.exit_calls: list[tuple[object, object, object]] = []

    def __enter__(self) -> FakeSpan:
        return self.span

    def __exit__(self, exc_type, exc, tb) -> None:
        self.exit_calls.append((exc_type, exc, tb))
        return None


def make_definition(
    *, suffix: str | None = None, case_id: UUID | None = None
) -> TestDefinition:
    return TestDefinition(
        name="test_traced",
        fn=lambda: None,
        module_path=Path("test_traced.py"),
        is_async=False,
        suffix=suffix,
        case_id=case_id,
    )


@pytest.mark.parametrize(
    ("suffix", "case_id", "expected_attributes"),
    [
        (
            "{'slug': 'example'}",
            UUID("00000000-0000-0000-0000-000000000001"),
            {
                "test.suffix": "{'slug': 'example'}",
                "test.case_id": "00000000-0000-0000-0000-000000000001",
            },
        ),
        (
            "00000000-0000-0000-0000-000000000001",
            None,
            {
                "test.suffix": "00000000-0000-0000-0000-000000000001",
            },
        ),
    ],
)
def test_test_tracer_records_root_span_metadata(
    monkeypatch,
    suffix: str | None,
    case_id: UUID | None,
    expected_attributes: dict[str, str],
):
    span = FakeSpan()
    scope = FakeSpanScope(span)
    monkeypatch.setattr(
        "rue.testing.tracing.otel_runtime.start_as_current_span",
        lambda _name: scope,
    )

    tracer = TestTracer(otel_enabled=True, otel_content=True)
    active_span = tracer.start_otel_root_span(
        make_definition(suffix=suffix, case_id=case_id)
    )

    assert active_span is span
    assert {
        key: span.attributes[key]
        for key in span.attributes
        if key in {"test.suffix", "test.case_id"}
    } == expected_attributes


def test_test_tracer_records_result_and_finishes_session(monkeypatch):
    span = FakeSpan(trace_id=0x1234)
    scope = FakeSpanScope(span)
    session = SimpleNamespace(root_span=span, execution_id=UUID(int=2))
    error = RuntimeError("boom")

    monkeypatch.setattr(
        "rue.testing.tracing.otel_runtime.start_as_current_span",
        lambda _name: scope,
    )
    monkeypatch.setattr(
        "rue.testing.tracing.otel_runtime.start_otel_trace",
        lambda root_span, *, run_id, execution_id, otel_content: session,
    )
    monkeypatch.setattr(
        "rue.testing.tracing.otel_runtime.finish_otel_trace",
        lambda current_session: current_session,
    )

    tracer = TestTracer(otel_enabled=True, otel_content=False)
    tracer.start_otel_root_span(make_definition())
    started = tracer.start_otel_trace(
        run_id=UUID(int=1), execution_id=UUID(int=2)
    )
    tracer.record_otel_result(
        TestResult(status=TestStatus.FAILED, duration_ms=12.5, error=error)
    )
    finished = tracer.finish_otel_trace()

    assert started is session
    assert finished is session
    assert tracer.completed_otel_trace_session is session
    assert tracer.otel_trace_session is None
    assert tracer.otel_trace_id == "00000000000000000000000000001234"
    assert scope.exit_calls == [(None, None, None)]
    assert span.attributes["test.status"] == "failed"
    assert span.attributes["test.duration_ms"] == 12.5
    assert span.status == (StatusCode.ERROR, "boom")
    assert span.exceptions == [error]
