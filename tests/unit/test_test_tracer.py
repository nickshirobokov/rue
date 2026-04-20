from types import SimpleNamespace
from uuid import UUID

import pytest
from opentelemetry.trace import StatusCode

from rue.config import Config
from rue.telemetry import OtelTraceArtifact
from rue.telemetry.otel.backend import OtelTelemetryBackend
from rue.testing.models import LoadedTestDef, TestResult, TestStatus
from rue.testing.tracing import build_test_tracer
from tests.unit.factories import make_definition as _make_definition


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


def make_definition(
    *, suffix: str | None = None, case_id: UUID | None = None
) -> LoadedTestDef:
    return _make_definition(
        "test_traced",
        module_path="test_traced.py",
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
    session = SimpleNamespace(
        root_span=span,
        run_id=UUID(int=1),
        execution_id=UUID(int=2),
        serialize=lambda: {
            "run_id": str(UUID(int=1)),
            "execution_id": str(UUID(int=2)),
            "spans": [],
        },
    )
    monkeypatch.setattr(
        "rue.telemetry.otel.backend.otel_runtime.start_as_current_span",
        lambda _name: scope,
    )
    monkeypatch.setattr(
        "rue.telemetry.otel.backend.otel_runtime.start_otel_trace",
        lambda *_args, **_kwargs: session,
    )

    tracer = build_test_tracer(
        config=Config.model_construct(otel=True),
        run_id=UUID(int=1),
    )
    tracer.start(make_definition(suffix=suffix, case_id=case_id), UUID(int=2))

    assert {
        key: span.attributes[key]
        for key in span.attributes
        if key in {"test.suffix", "test.case_id"}
    } == expected_attributes


def test_test_tracer_records_result_and_emits_otel_artifact(monkeypatch):
    span = FakeSpan(trace_id=0x1234)
    scope = FakeSpanScope(span)
    session = SimpleNamespace(root_span=span, execution_id=UUID(int=2))
    error = RuntimeError("boom")

    def _serialize():
        return {
            "run_id": str(UUID(int=1)),
            "execution_id": str(UUID(int=2)),
            "spans": [{"name": "test.test_traced", "parent_id": None}],
        }

    session.run_id = UUID(int=1)
    session.serialize = _serialize

    monkeypatch.setattr(
        "rue.telemetry.otel.backend.otel_runtime.start_as_current_span",
        lambda _name: scope,
    )
    monkeypatch.setattr(
        "rue.telemetry.otel.backend.otel_runtime.start_otel_trace",
        lambda *_args, **_kwargs: session,
    )
    monkeypatch.setattr(
        "rue.telemetry.otel.backend.otel_runtime.finish_otel_trace",
        lambda current_session: current_session,
    )

    tracer = build_test_tracer(
        config=Config.model_construct(otel=True),
        run_id=UUID(int=1),
    )
    tracer.start(make_definition(), UUID(int=2))
    tracer.record_result(
        TestResult(status=TestStatus.FAILED, duration_ms=12.5, error=error)
    )
    artifacts = tracer.finish()

    backend = tracer.get_backend(OtelTelemetryBackend)
    assert backend is not None
    assert backend.active_session is None
    assert artifacts == (
        OtelTraceArtifact(
            run_id=UUID(int=1),
            execution_id=UUID(int=2),
            trace_id="00000000000000000000000000001234",
            spans=[{"name": "test.test_traced", "parent_id": None}],
        ),
    )
    assert scope.exit_calls == [(None, None, None)]
    assert span.attributes["test.status"] == "failed"
    assert span.attributes["test.duration_ms"] == 12.5
    assert span.status == (StatusCode.ERROR, "boom")
    assert span.exceptions == [error]


def test_test_tracer_supports_backend_lookup_and_empty_finish():
    tracer = build_test_tracer(
        config=Config.model_construct(otel=True),
        run_id=UUID(int=1),
    )

    assert isinstance(
        tracer.get_backend(OtelTelemetryBackend),
        OtelTelemetryBackend,
    )
    assert tracer.finish() == ()


def test_build_test_tracer_adds_otel_backend_when_enabled():
    tracer = build_test_tracer(
        config=Config.model_construct(otel=True),
        run_id=UUID(int=1),
    )

    assert len(tracer.backends) == 1


def test_build_test_tracer_skips_otel_when_disabled():
    tracer = build_test_tracer(
        config=Config.model_construct(otel=False),
        run_id=UUID(int=1),
    )

    assert tracer.backends == ()
