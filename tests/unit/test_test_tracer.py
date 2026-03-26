from pathlib import Path
from uuid import UUID

from rue.telemetry.otel.test_span_manager import OtelTestSpanManager
from rue.testing.models import TestItem


class FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def __enter__(self) -> "FakeSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb
        return None

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class FakeSpanContext:
    def __init__(self, span: FakeSpan) -> None:
        self._span = span

    def __call__(self, _name: str) -> FakeSpan:
        return self._span


def make_item(*, suffix: str | None = None, case_id: UUID | None = None) -> TestItem:
    return TestItem(
        name="test_traced",
        fn=lambda: None,
        module_path=Path("test_traced.py"),
        is_async=False,
        suffix=suffix,
        case_id=case_id,
    )


def test_tracer_records_suffix_and_case_id(monkeypatch):
    span = FakeSpan()
    monkeypatch.setattr(
        "rue.telemetry.otel.test_span_manager.otel_runtime.start_as_current_span",
        FakeSpanContext(span),
    )
    monkeypatch.setattr(
        "rue.telemetry.otel.test_span_manager.otel_runtime.is_configured",
        lambda: True,
    )

    tracer = OtelTestSpanManager(enabled=True)
    item = make_item(
        suffix="{'slug': 'example'}",
        case_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    with tracer.span(item) as active_span:
        assert active_span is span

    assert span.attributes["test.id_suffix"] == "{'slug': 'example'}"
    assert span.attributes["test.case_id"] == "00000000-0000-0000-0000-000000000001"


def test_tracer_does_not_infer_case_id_from_suffix(monkeypatch):
    span = FakeSpan()
    monkeypatch.setattr(
        "rue.telemetry.otel.test_span_manager.otel_runtime.start_as_current_span",
        FakeSpanContext(span),
    )
    monkeypatch.setattr(
        "rue.telemetry.otel.test_span_manager.otel_runtime.is_configured",
        lambda: True,
    )

    tracer = OtelTestSpanManager(enabled=True)
    item = make_item(suffix="00000000-0000-0000-0000-000000000001")

    with tracer.span(item):
        pass

    assert span.attributes["test.id_suffix"] == "00000000-0000-0000-0000-000000000001"
    assert "test.case_id" not in span.attributes
