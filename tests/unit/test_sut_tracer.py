from types import SimpleNamespace
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
from opentelemetry.trace import ProxyTracerProvider

from rue.context.runtime import CURRENT_SUT_SPAN_IDS
from rue.resources.sut.tracer import SUTTracer


class FakeSpan:
    def __init__(self, span_id: int) -> None:
        self.attributes: dict[str, object] = {}
        self._context = SimpleNamespace(span_id=span_id)

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def get_span_context(self) -> SimpleNamespace:
        return self._context


class FakeSpanScope:
    def __init__(self, span: FakeSpan) -> None:
        self.span = span

    def __enter__(self) -> FakeSpan:
        return self.span

    def __exit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb


class FakeReadableSpan:
    def __init__(
        self, name: str, span_id: int, parent_id: int | None = None
    ) -> None:
        self.name = name
        self.context = SimpleNamespace(span_id=span_id)
        self.parent = (
            None
            if parent_id is None
            else SimpleNamespace(span_id=parent_id)
        )


class FakeSession:
    def __init__(self) -> None:
        self.spans: list[FakeReadableSpan] = []
        self.owners: dict[int, int] = {}

    def get_spans(self) -> list[FakeReadableSpan]:
        return list(self.spans)

    def get_sut_owner(self, span_id: int) -> int | None:
        return self.owners.get(span_id)


def make_span_factory(span_ids: list[int]):
    created: list[FakeSpan] = []
    names: list[str] = []
    remaining_ids = iter(span_ids)

    def start_as_current_span(name: str) -> FakeSpanScope:
        names.append(name)
        span = FakeSpan(next(remaining_ids))
        created.append(span)
        return FakeSpanScope(span)

    return created, names, start_as_current_span


def test_wraps_sync_calls_with_content(monkeypatch: pytest.MonkeyPatch):
    created, names, start_as_current_span = make_span_factory([101])
    monkeypatch.setattr(
        "rue.resources.sut.tracer.otel_runtime.start_as_current_span",
        start_as_current_span,
    )
    session = FakeSession()
    tracer = SUTTracer("pipeline")
    tracer.reset(UUID(int=1))
    tracer.activate(session)
    seen: dict[str, object] = {}

    def run(x: int, *, y: int) -> str:
        seen["span_ids"] = CURRENT_SUT_SPAN_IDS.get()
        return f"{x}:{y}"

    wrapped = tracer.wrap("__call__", run, is_async=False)
    result = wrapped(2, y=3)

    assert result == "2:3"
    assert seen["span_ids"] == (101,)
    assert names == ["sut.pipeline.__call__"]
    assert created[0].attributes == {
        "rue.sut": True,
        "rue.sut.name": "pipeline",
        "rue.sut.method": "__call__",
        "sut.input.args": "(2,)",
        "sut.input.kwargs": "{'y': 3}",
        "sut.output": "'2:3'",
    }


@pytest.mark.asyncio
async def test_wraps_async_calls_with_content(
    monkeypatch: pytest.MonkeyPatch,
):
    created, names, start_as_current_span = make_span_factory([202])
    monkeypatch.setattr(
        "rue.resources.sut.tracer.otel_runtime.start_as_current_span",
        start_as_current_span,
    )
    session = FakeSession()
    tracer = SUTTracer("service")
    tracer.reset(UUID(int=1))
    tracer.activate(session)
    seen: dict[str, object] = {}

    async def run(value: int) -> list[int]:
        seen["span_ids"] = CURRENT_SUT_SPAN_IDS.get()
        return [value]

    wrapped = tracer.wrap("run", run, is_async=True)
    result = await wrapped(5)

    assert result == [5]
    assert seen["span_ids"] == (202,)
    assert names == ["sut.service.run"]
    assert created[0].attributes == {
        "rue.sut": True,
        "rue.sut.name": "service",
        "rue.sut.method": "run",
        "sut.input.args": "(5,)",
        "sut.output": "[5]",
    }


def test_skips_tracing_without_active_trace(monkeypatch: pytest.MonkeyPatch):
    def fail_start(_name: str) -> FakeSpanScope:
        raise AssertionError("unexpected span creation")

    monkeypatch.setattr(
        "rue.resources.sut.tracer.otel_runtime.start_as_current_span",
        fail_start,
    )
    monkeypatch.setattr(
        "rue.resources.sut.tracer.trace.get_tracer_provider",
        ProxyTracerProvider,
    )
    tracer = SUTTracer("plain")
    seen: list[tuple[int, ...]] = []

    def run(value: int) -> int:
        seen.append(CURRENT_SUT_SPAN_IDS.get())
        return value * 2

    wrapped = tracer.wrap("__call__", run, is_async=False)

    assert wrapped(4) == 8
    assert seen == [()]


def test_traces_with_sdk_provider_and_no_session(monkeypatch: pytest.MonkeyPatch):
    """SUT emits spans to a real SdkTracerProvider even without a Rue session."""
    created, names, start_as_current_span = make_span_factory([501])
    monkeypatch.setattr(
        "rue.resources.sut.tracer.otel_runtime.start_as_current_span",
        start_as_current_span,
    )
    monkeypatch.setattr(
        "rue.resources.sut.tracer.trace.get_tracer_provider",
        SdkTracerProvider,
    )
    tracer = SUTTracer("standalone")

    def run(value: int) -> int:
        return value + 1

    wrapped = tracer.wrap("__call__", run, is_async=False)
    result = wrapped(10)

    assert result == 11
    assert names == ["sut.standalone.__call__"]
    assert created[0].attributes["rue.sut.name"] == "standalone"
    assert created[0].attributes["sut.input.args"] == "(10,)"
    assert created[0].attributes["sut.output"] == "11"


def test_resolves_child_and_llm_spans_and_resets_per_execution(
    monkeypatch: pytest.MonkeyPatch,
):
    created, _, start_as_current_span = make_span_factory([301])
    monkeypatch.setattr(
        "rue.resources.sut.tracer.otel_runtime.start_as_current_span",
        start_as_current_span,
    )
    session = FakeSession()
    tracer = SUTTracer("pipeline")
    tracer.reset(UUID(int=1))
    tracer.activate(session)
    wrapped = tracer.wrap("__call__", lambda: "ok", is_async=False)

    assert wrapped() == "ok"
    root_span_id = created[0].get_span_context().span_id
    session.spans = [
        FakeReadableSpan("sut.pipeline.__call__", root_span_id),
        FakeReadableSpan("child_step", 302, root_span_id),
        FakeReadableSpan("openai.responses.create", 303),
        FakeReadableSpan("unrelated", 304),
    ]
    session.owners = {303: root_span_id}

    assert [span.name for span in tracer.get_root_spans()] == [
        "sut.pipeline.__call__"
    ]
    assert {span.name for span in tracer.get_all_spans()} == {
        "sut.pipeline.__call__",
        "child_step",
        "openai.responses.create",
    }
    assert [span.name for span in tracer.get_llm_spans()] == [
        "openai.responses.create"
    ]

    tracer.reset(UUID(int=2))
    tracer.activate(session)
    assert tracer.get_root_spans() == []
