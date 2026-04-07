"""System-under-test wrapper for traced call surfaces."""

from __future__ import annotations

import functools
import inspect
import types
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Generic, cast
from uuid import UUID

from opentelemetry.sdk.trace import ReadableSpan
from pydantic import BaseModel
from pydantic.experimental.arguments_schema import generate_arguments_schema
from pydantic_ai import ModelRequest, ModelResponse
from pydantic_core import ArgsKwargs, SchemaValidator
from typing_extensions import TypeVar

from rue.context.runtime import CURRENT_TEST_TRACER
from rue.telemetry.otel.runtime import OtelTraceSession
from rue.testing.models.case import Case
from rue.testing.sut.tracer import SUTTracer


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
        self._method_specs = {
            method_name: self._create_method_spec(instance, method_name)
            for method_name in self.methods
        }
        match name, getattr(instance, "__name__", None):
            case (str() as resolved_name, _):
                resolved_sut_name = resolved_name
            case (None, str() as resolved_name):
                resolved_sut_name = resolved_name
            case _:
                resolved_sut_name = type(instance).__name__
        self._tracer = SUTTracer(resolved_sut_name)
        self._name = resolved_sut_name
        test_tracer = CURRENT_TEST_TRACER.get()
        if test_tracer is not None and test_tracer.otel_trace_session is not None:
            self._tracer.activate(
                test_tracer.otel_trace_session,
                otel_content=test_tracer.records_otel_content,
            )
        self.instance: InstanceT = self._wrap_instance(instance)

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value
        self._tracer.name = value

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
        return self._tracer.get_sut_spans()

    def get_child_spans(self) -> list[ReadableSpan]:
        return self._tracer.get_child_spans()

    def get_llm_calls(self) -> list[ReadableSpan]:
        return self._tracer.get_llm_calls()

    def reset_trace_state(self, execution_id: UUID | None) -> None:
        self._tracer.reset(execution_id)

    def activate_trace(
        self, session: OtelTraceSession, *, otel_content: bool = True
    ) -> None:
        self._tracer.activate(session, otel_content=otel_content)

    def deactivate_trace(self) -> None:
        self._tracer.deactivate()

    @contextmanager
    def tracing(self, *, otel_content: bool = True) -> Iterator[None]:
        with self._tracer.tracing(otel_content=otel_content):
            yield

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
            wrapped_callable = self._tracer.wrap(
                spec.name,
                spec.original_callable,
                is_async=spec.is_async,
            )

            if method_name == "__call__":
                if isinstance(instance, _BARE_CALLABLE_TYPES):
                    wrapped_instance = wrapped_callable
                    continue
                wrapped_instance = _CallableProxy(instance, wrapped_callable)
                continue

            setattr(instance, method_name, wrapped_callable)

        return cast("InstanceT", wrapped_instance)
