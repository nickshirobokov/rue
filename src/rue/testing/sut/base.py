"""System-under-test wrapper for traced call surfaces."""

from __future__ import annotations

import functools
import inspect
import types
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Generic, cast
from uuid import UUID

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import Span
from pydantic import BaseModel
from pydantic.experimental.arguments_schema import generate_arguments_schema
from pydantic_ai import ModelRequest, ModelResponse
from pydantic_core import ArgsKwargs, SchemaValidator
from typing_extensions import TypeVar

from rue.context.runtime import (
    CURRENT_SUT_SPAN_IDS,
    CURRENT_TEST_TRACER,
    bind,
)
from rue.telemetry.otel.runtime import otel_runtime
from rue.testing.models.case import Case


Message = ModelRequest | ModelResponse
InstanceT = TypeVar("InstanceT", default=object)

_BARE_CALLABLE_TYPES = (
    types.FunctionType,
    types.MethodType,
    types.MethodWrapperType,
    functools.partial,
)


@dataclass(slots=True)
class _MethodSpec:
    name: str
    original_callable: Callable[..., object]
    validator: SchemaValidator
    is_async: bool
    

class _CallableProxy:
    _target: object
    _call_wrapper: Callable[..., object]

    def __init__(
        self, target: object, call_wrapper: Callable[..., object]
    ) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_call_wrapper", call_wrapper)

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self._call_wrapper(*args, **kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(self._target, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._target, name, value)


class SUT(Generic[InstanceT]):
    def __init__(
        self,
        instance: InstanceT,
        methods: Sequence[str] | None = None,
        name: str | None = None,
    ) -> None:
        self.methods = tuple(dict.fromkeys(methods or ["__call__"]))
        self._otel_execution_id: ContextVar[UUID | None] = ContextVar(
            f"sut_{id(self)}_otel_execution_id",
            default=None,
        )
        self._otel_span_ids: ContextVar[tuple[int, ...]] = ContextVar(
            f"sut_{id(self)}_otel_span_ids",
            default=(),
        )
        self._method_specs = {
            method_name: self._create_method_spec(instance, method_name)
            for method_name in self.methods
        }
        match name, getattr(instance, "__name__", None):
            case (str() as resolved_name, _):
                self.name = resolved_name
            case (None, str() as resolved_name):
                self.name = resolved_name
            case _:
                self.name = type(instance).__name__
        self.instance: InstanceT = self._wrap_instance(instance)

    def get_ai_requests(self) -> list[ModelRequest]:
        raise NotImplementedError("Not implemented")

    def get_ai_responses(self) -> list[ModelResponse]:
        raise NotImplementedError("Not implemented")

    def get_message_history(self) -> list[Message]:
        raise NotImplementedError("Not implemented")

    def get_tool_calls(self) -> list[object]:
        raise NotImplementedError("Not implemented")

    def validate_cases(
        self, cases: Sequence[Case[Any, Any]], method_name: str
    ) -> None:
        spec = self._method_specs.get(method_name)
        if spec is None:
            raise ValueError(f"Method '{method_name}' not found in SUT")

        for case in cases:
            match case.inputs:
                case dict() as input_values:
                    pass
                case BaseModel() as model:
                    input_values = dict(model)
                case Mapping() as mapping:
                    input_values = dict(mapping)
                case value if is_dataclass(value) and not isinstance(
                    value, type
                ):
                    input_values = {
                        field.name: getattr(value, field.name)
                        for field in fields(value)
                    }
                case value:
                    raise TypeError(
                        "Case inputs must be a dict, mapping, BaseModel, or dataclass instance. "
                        f"Got: {type(value).__name__}"
                    )
            parsed_args = ArgsKwargs(args=(), kwargs=input_values)
            spec.validator.validate_python(parsed_args)

    def get_sut_spans(self) -> list[ReadableSpan]:
        tracer = CURRENT_TEST_TRACER.get()
        if tracer is None or tracer.otel_trace_session is None:
            raise RuntimeError(
                "OpenTelemetry is not enabled or this SUT has not been traced yet."
            )
        span_ids = set(self._otel_span_ids.get())
        if not span_ids:
            return []
        return [
            span
            for span in tracer.otel_trace_session.get_spans()
            if span.context.span_id in span_ids
        ]

    def get_child_spans(self) -> list[ReadableSpan]:
        tracer = CURRENT_TEST_TRACER.get()
        if tracer is None or tracer.otel_trace_session is None:
            raise RuntimeError(
                "OpenTelemetry is not enabled or this SUT has not been traced yet."
            )
        sut_spans = self.get_sut_spans()
        if not sut_spans:
            return []

        root_ids = {span.context.span_id for span in sut_spans}
        descendant_ids = set(root_ids)
        spans = tracer.otel_trace_session.get_spans()

        changed = True
        while changed:
            changed = False
            for span in spans:
                span_id = span.context.span_id
                if span_id in descendant_ids:
                    continue
                if (
                    span.parent is not None
                    and span.parent.span_id in descendant_ids
                ):
                    descendant_ids.add(span_id)
                    changed = True
                    continue
                owner_span_id = tracer.otel_trace_session.get_sut_owner(span_id)
                if owner_span_id in root_ids:
                    descendant_ids.add(span_id)
                    changed = True

        return [
            span for span in spans if span.context.span_id in descendant_ids
        ]

    def get_llm_calls(self) -> list[ReadableSpan]:
        return [
            span
            for span in self.get_child_spans()
            if span.name.startswith(("openai.", "anthropic.", "gen_ai."))
        ]

    def _create_method_spec(
        self, instance: object, method_name: str
    ) -> _MethodSpec:
        target_callable: Callable[..., object]
        if method_name == "__call__" and isinstance(instance, _BARE_CALLABLE_TYPES):
            target_callable = instance
        else:
            missing = object()
            raw_callable = getattr(cast(Any, instance), method_name, missing)
            if raw_callable is missing:
                raise ValueError(
                    f"Method '{method_name}' not found in instance"
                )
            if not callable(raw_callable):
                raise ValueError(f"Method '{method_name}' is not a callable")
            target_callable = cast(Callable[..., object], raw_callable)

        args_schema = generate_arguments_schema(
            target_callable,
            parameters_callback=lambda _, param_name, __: (
                "skip" if param_name in {"self", "cls"} else None
            ),
        )
        return _MethodSpec(
            name=method_name,
            original_callable=target_callable,
            validator=SchemaValidator(args_schema),
            is_async=inspect.iscoroutinefunction(target_callable),
        )

    def _wrap_instance(self, instance: InstanceT) -> InstanceT:
        wrapped_instance: object = instance
        for method_name in self.methods:
            spec = self._method_specs[method_name]
            wrapped_callable = self._make_traced_callable(spec)

            if method_name == "__call__":
                if isinstance(instance, _BARE_CALLABLE_TYPES):
                    wrapped_instance = wrapped_callable
                    continue
                wrapped_instance = _CallableProxy(instance, wrapped_callable)
                continue

            setattr(instance, method_name, wrapped_callable)

        return cast("InstanceT", wrapped_instance)

    def _make_traced_callable(self, spec: _MethodSpec) -> Callable[..., object]:
        if spec.is_async:

            @functools.wraps(spec.original_callable)
            async def async_wrapped(
                *args: object, **kwargs: object
            ) -> object:
                tracer = CURRENT_TEST_TRACER.get()
                if tracer is None or not tracer.has_otel_trace:
                    return await cast(
                        Awaitable[object],
                        spec.original_callable(*args, **kwargs),
                    )
                return await self._trace_async(spec, *args, **kwargs)

            return async_wrapped

        @functools.wraps(spec.original_callable)
        def sync_wrapped(*args: object, **kwargs: object) -> object:
            tracer = CURRENT_TEST_TRACER.get()
            if tracer is None or not tracer.has_otel_trace:
                return spec.original_callable(*args, **kwargs)
            return self._trace_sync(spec, *args, **kwargs)

        return sync_wrapped

    def _trace_sync(
        self, spec: _MethodSpec, *args: object, **kwargs: object
    ) -> object:
        tracer = CURRENT_TEST_TRACER.get()
        record_content = tracer is not None and tracer.records_otel_content
        with otel_runtime.start_as_current_span(
            f"sut.{self.name}.{spec.name}"
        ) as span:
            span_id = self._set_span_attrs(span, spec.name)
            span_ids = (*CURRENT_SUT_SPAN_IDS.get(), span_id)
            with bind(CURRENT_SUT_SPAN_IDS, span_ids):
                _set_input_attrs(span, args, kwargs, record_content)
                result = spec.original_callable(*args, **kwargs)
                _set_output_attrs(span, result, record_content)
                return result

    async def _trace_async(
        self, spec: _MethodSpec, *args: object, **kwargs: object
    ) -> object:
        tracer = CURRENT_TEST_TRACER.get()
        record_content = tracer is not None and tracer.records_otel_content
        with otel_runtime.start_as_current_span(
            f"sut.{self.name}.{spec.name}"
        ) as span:
            span_id = self._set_span_attrs(span, spec.name)
            span_ids = (*CURRENT_SUT_SPAN_IDS.get(), span_id)
            with bind(CURRENT_SUT_SPAN_IDS, span_ids):
                _set_input_attrs(span, args, kwargs, record_content)
                result = await cast(
                    Awaitable[object],
                    spec.original_callable(*args, **kwargs),
                )
                _set_output_attrs(span, result, record_content)
                return result

    def _set_span_attrs(self, span: Span, method_name: str) -> int:
        span.set_attribute("rue.sut", True)
        span.set_attribute("rue.sut.name", self.name)
        span.set_attribute("rue.sut.method", method_name)
        span_id = span.get_span_context().span_id
        self._otel_span_ids.set((*self._otel_span_ids.get(), span_id))
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
