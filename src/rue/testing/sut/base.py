from __future__ import annotations

import functools
import inspect
import types
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from typing import Any

from pydantic import BaseModel
from pydantic.experimental.arguments_schema import generate_arguments_schema
from pydantic_core import ArgsKwargs, SchemaValidator

from rue.context.runtime import CURRENT_TEST_TRACER
from rue.testing.models.case import Case
from rue.telemetry.otel.runtime import otel_runtime


class SUT:
    def __init__(
        self,
        instance: object,
        method: str = "__call__",
        name: str | None = None,
        validate_cases: Sequence[Case[Any, Any]] | None = None,
    ):
        self.instance = instance
        self.method = method

        # Resolve the target callable
        target = getattr(self.instance, self.method, None)
        match target:
            case types.FunctionType() | types.MethodType() | types.MethodWrapperType() | functools.partial():
                self.target_callable = target
            case None:
                raise ValueError(f"Method '{self.method}' not found in instance")
            case _:
                raise ValueError(f"Method '{self.method}' is not a callable")

        assert self.target_callable is not None

        # Check if the target callable is asynchronous
        self.is_async = inspect.iscoroutinefunction(self.target_callable)

        # Generate the arguments schema
        self.args_schema = generate_arguments_schema(
            self.target_callable,
            parameters_callback=(
                lambda index, name, annotation: (
                    "skip" if name in {"self", "cls"} else None
                )
            ),
        )

        # Create the validator
        self.validator = SchemaValidator(self.args_schema)

        # Resolve the name
        match name, getattr(instance, "__name__", None), getattr(self.target_callable, "__name__", None):
            case (str() as n, _, _):
                self.name = n
            case (None, str() as n, _):
                self.name = n
            case (None, _, str() as n):
                self.name = n
            case _:
                self.name = type(instance).__name__

        # Validate the cases
        if validate_cases:
            self.validate_cases(validate_cases)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        tracer = CURRENT_TEST_TRACER.get()
        if tracer is None or not tracer.has_otel_trace:
            return self.target_callable(*args, **kwargs)

        if self.is_async:
            return self._call_async(*args, **kwargs)
        return self._call_sync(*args, **kwargs)

    def validate_cases(self, cases: Sequence[Case[Any, Any]]) -> None:
        for case in cases:
            match case.inputs:
                case dict() as input_values:
                    pass
                case BaseModel() as model:
                    input_values = dict(model)
                case Mapping() as mapping:
                    input_values = dict(mapping)
                case value if is_dataclass(value) and not isinstance(value, type):
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
            self.validator.validate_python(parsed_args)

    def _call_sync(self, *args: Any, **kwargs: Any) -> Any:
        with otel_runtime.start_as_current_span(f"sut.{self.name}") as span:
            span.set_attribute("rue.sut", True)
            span.set_attribute("rue.sut.name", self.name)
            _set_input_attrs(span, args, kwargs)
            result = self.target_callable(*args, **kwargs)
            _set_output_attrs(span, result)
            return result

    async def _call_async(self, *args: Any, **kwargs: Any) -> Any:
        with otel_runtime.start_as_current_span(f"sut.{self.name}") as span:
            span.set_attribute("rue.sut", True)
            span.set_attribute("rue.sut.name", self.name)
            _set_input_attrs(span, args, kwargs)
            result = await self.target_callable(*args, **kwargs)
            _set_output_attrs(span, result)
            return result


def _set_input_attrs(
    span: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> None:
    tracer = CURRENT_TEST_TRACER.get()
    if tracer is None or not tracer.records_otel_content:
        span.set_attribute("sut.input.count", len(args) + len(kwargs))
        return

    if args:
        span.set_attribute("sut.input.args", repr(args))
    if kwargs:
        span.set_attribute("sut.input.kwargs", repr(kwargs))


def _set_output_attrs(span: Any, result: Any) -> None:
    tracer = CURRENT_TEST_TRACER.get()
    if tracer is None or not tracer.records_otel_content:
        span.set_attribute("sut.output.type", type(result).__name__)
        return

    span.set_attribute("sut.output", repr(result))
