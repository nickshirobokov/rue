"""Internal tracing helper for SUT-wrapped methods."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import cast
from uuid import UUID, uuid4

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider as SdkTracerProvider
from opentelemetry.trace import Span

from rue.context.runtime import CURRENT_SUT_SPAN_IDS, bind
from rue.telemetry.otel.runtime import OtelTraceSession, otel_runtime


class SUTTracer:
    def __init__(self, name: str) -> None:
        self.name = name
        self._session: OtelTraceSession | None = None
        self._otel_content: bool = True
        self._execution_id: ContextVar[UUID | None] = ContextVar(
            f"sut_{id(self)}_otel_execution_id",
            default=None,
        )
        self._span_ids: ContextVar[tuple[int, ...]] = ContextVar(
            f"sut_{id(self)}_otel_span_ids",
            default=(),
        )

    def activate(self, session: OtelTraceSession, *, otel_content: bool = True) -> None:
        self._session = session
        self._otel_content = otel_content

    def deactivate(self) -> None:
        self._session = None

    def reset(self, execution_id: UUID | None) -> None:
        if self._execution_id.get() == execution_id:
            return
        self._execution_id.set(execution_id)
        self._span_ids.set(())
        self._session = None

    @contextmanager
    def tracing(self, *, otel_content: bool = True) -> Iterator[None]:
        otel_runtime.configure()
        with otel_runtime.start_as_current_span(f"sut.{self.name}") as root_span:
            session = otel_runtime.start_otel_trace(
                root_span,
                run_id=uuid4(),
                execution_id=uuid4(),
                otel_content=otel_content,
            )
            self.activate(session, otel_content=otel_content)
            try:
                yield
            finally:
                self.deactivate()
                otel_runtime.finish_otel_trace(session)

    def wrap(
        self,
        method_name: str,
        original_callable: Callable[..., object],
        *,
        is_async: bool,
    ) -> Callable[..., object]:
        if is_async:

            @functools.wraps(original_callable)
            async def async_wrapped(*args: object, **kwargs: object) -> object:
                if not self._should_trace():
                    return await cast(
                        Awaitable[object],
                        original_callable(*args, **kwargs),
                    )
                return await self._trace_async(
                    method_name,
                    original_callable,
                    *args,
                    **kwargs,
                )

            return async_wrapped

        @functools.wraps(original_callable)
        def sync_wrapped(*args: object, **kwargs: object) -> object:
            if not self._should_trace():
                return original_callable(*args, **kwargs)
            return self._trace_sync(
                method_name,
                original_callable,
                *args,
                **kwargs,
            )

        return sync_wrapped

    def get_sut_spans(self) -> list[ReadableSpan]:
        session = self._require_session()
        span_ids = set(self._span_ids.get())
        if not span_ids:
            return []
        return [
            span for span in session.get_spans() if span.context.span_id in span_ids
        ]

    def get_child_spans(self) -> list[ReadableSpan]:
        session = self._require_session()
        sut_spans = self.get_sut_spans()
        if not sut_spans:
            return []

        root_ids = {span.context.span_id for span in sut_spans}
        descendant_ids = set(root_ids)
        spans = session.get_spans()

        changed = True
        while changed:
            changed = False
            for span in spans:
                span_id = span.context.span_id
                if span_id in descendant_ids:
                    continue
                if span.parent is not None and span.parent.span_id in descendant_ids:
                    descendant_ids.add(span_id)
                    changed = True
                    continue
                owner_span_id = session.get_sut_owner(span_id)
                if owner_span_id in root_ids:
                    descendant_ids.add(span_id)
                    changed = True

        return [span for span in spans if span.context.span_id in descendant_ids]

    def get_llm_calls(self) -> list[ReadableSpan]:
        return [
            span
            for span in self.get_child_spans()
            if span.name.startswith(("openai.", "anthropic.", "gen_ai."))
        ]

    def _require_session(self) -> OtelTraceSession:
        if self._session is None:
            raise RuntimeError(
                "OpenTelemetry is not enabled or this SUT has not been traced yet."
            )
        return self._session

    def _should_trace(self) -> bool:
        if self._session is not None:
            return True
        return isinstance(trace.get_tracer_provider(), SdkTracerProvider)

    def _records_content(self) -> bool:
        if self._session is not None:
            return self._otel_content
        return self._should_trace() and self._otel_content

    def _trace_sync(
        self,
        method_name: str,
        original_callable: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object:
        record_content = self._records_content()
        with otel_runtime.start_as_current_span(f"sut.{self.name}.{method_name}") as span:
            span_id = self._set_span_attrs(span, method_name)
            span_ids = (*CURRENT_SUT_SPAN_IDS.get(), span_id)
            with bind(CURRENT_SUT_SPAN_IDS, span_ids):
                _set_input_attrs(span, args, kwargs, record_content)
                result = original_callable(*args, **kwargs)
                _set_output_attrs(span, result, record_content)
                return result

    async def _trace_async(
        self,
        method_name: str,
        original_callable: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object:
        record_content = self._records_content()
        with otel_runtime.start_as_current_span(f"sut.{self.name}.{method_name}") as span:
            span_id = self._set_span_attrs(span, method_name)
            span_ids = (*CURRENT_SUT_SPAN_IDS.get(), span_id)
            with bind(CURRENT_SUT_SPAN_IDS, span_ids):
                _set_input_attrs(span, args, kwargs, record_content)
                result = await cast(
                    Awaitable[object],
                    original_callable(*args, **kwargs),
                )
                _set_output_attrs(span, result, record_content)
                return result

    def _set_span_attrs(self, span: Span, method_name: str) -> int:
        span.set_attribute("rue.sut", True)
        span.set_attribute("rue.sut.name", self.name)
        span.set_attribute("rue.sut.method", method_name)
        span_id = span.get_span_context().span_id
        self._span_ids.set((*self._span_ids.get(), span_id))
        return span_id


def _set_input_attrs(
    span: Span,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    record_content: bool,
) -> None:
    if not record_content:
        span.set_attribute("sut.input.count", len(args) + len(kwargs))
        return
    if args:
        span.set_attribute("sut.input.args", repr(args))
    if kwargs:
        span.set_attribute("sut.input.kwargs", repr(kwargs))


def _set_output_attrs(span: Span, result: object, record_content: bool) -> None:
    if not record_content:
        span.set_attribute("sut.output.type", type(result).__name__)
        return
    span.set_attribute("sut.output", repr(result))
