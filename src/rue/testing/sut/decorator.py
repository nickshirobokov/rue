"""System-Under-Test (SUT) decorator for traced test targets.

The @sut decorator registers a callable as a traced resource that can be
injected into Rue tests. All invocations are wrapped in OpenTelemetry spans,
and any LLM calls made within are automatically captured as child spans.
"""

import functools
import inspect
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from typing import Any, ParamSpec, TypeVar

from pydantic import BaseModel
from pydantic.experimental.arguments_schema import generate_arguments_schema
from pydantic_core import ArgsKwargs, SchemaValidator

from rue.context import get_test_tracer
from rue.resources import Scope, resource
from rue.testing.models.case import Case
from rue.telemetry.otel.runtime import otel_runtime


P = ParamSpec("P")
T = TypeVar("T")


def sut(
    fn: Callable[..., Any] | None = None,
    *,
    scope: Scope | str = Scope.CASE,
    method: str = "__call__",
    validate_cases: list[Case[Any, Any]] | None = None,
) -> Any:
    """Register a callable as a traced system-under-test resource.

    Supports function factories only. The decorated function is treated as a
    resource factory and should return (or yield) either:
    - a FunctionType, MethodType, or partial to trace, or
    - an instance whose method should be traced.

    Args:
        fn: The factory function to register as SUT.
        scope: Resource scope for the factory.
        method: The method to trace for non-callable instance values.
        validate_cases: Optional test cases to validate against resolved SUT signature.

    Example:
        @sut
        def my_agent_factory(client):
            def my_agent(prompt: str) -> str:
                return client.generate(prompt)
            return my_agent

        def test_sut(my_agent_factory):
            result = my_agent("Hello")
    """
    normalized_validate_cases = list(validate_cases) if validate_cases else []

    if fn is None:
        return lambda factory: sut(
            factory,
            scope=scope,
            method=method,
            validate_cases=normalized_validate_cases,
        )

    if not isinstance(fn, types.FunctionType):
        raise TypeError(f"""@sut can only decorate functions.
        Got: {type(fn).__name__}
        Expected: FunctionType
        """)

    factory_name = fn.__name__

    def on_resolve(sut_instance: Any) -> Any:
        # TODO: Register SUT in the DB with dependencies
        match sut_instance:
            case types.FunctionType() | types.MethodType() | functools.partial():
                if normalized_validate_cases:
                    _validate_cases(normalized_validate_cases, sut_instance)
                return _trace_callable(sut_instance, sut_name=factory_name)

            case _ if isinstance(getattr(sut_instance, method, None), types.MethodType):
                if normalized_validate_cases:
                    _validate_cases(normalized_validate_cases, getattr(sut_instance, method))
                return _trace_instance_method(sut_instance, sut_name=factory_name, method=method)

            case _:
                msg = f"""SUT '{factory_name}' resolved to unsupported type:
                {type(sut_instance).__name__}
                Expected a FunctionType, MethodType, or an instance with a MethodType.
                """
                raise TypeError(msg)

    return resource(
        fn,
        scope=scope,
        on_resolve=on_resolve,
    )


def _validate_cases(cases: Sequence[Case[Any, Any]], sut: Callable[..., Any]):
    schema = generate_arguments_schema(
        sut,
        parameters_callback=(
            lambda index, name, annotation: "skip" if name in {"self", "cls"} else None
        ),
    )
    validator = SchemaValidator(schema)
    for case in cases:
        match case.inputs:
            case dict() as input_values:
                pass
            case BaseModel() as model:
                input_values = dict(model)
            case Mapping() as mapping:
                input_values = dict(mapping)
            case value if is_dataclass(value) and not isinstance(value, type):
                input_values = {field.name: getattr(value, field.name) for field in fields(value)}
            case value:
                msg = (
                    "Case inputs must be a dict, mapping, BaseModel, or dataclass instance. "
                    f"Got: {type(value).__name__}"
                )
                raise TypeError(msg)
        parsed_args = ArgsKwargs(args=(), kwargs=input_values)
        validator.validate_python(parsed_args)


def _trace_callable(fn: Callable[..., Any], *, sut_name: str) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def traced_async(*args: Any, **kwargs: Any) -> Any:
            tracer = get_test_tracer()
            if tracer is None or tracer.otel_trace_session is None:
                return await fn(*args, **kwargs)

            with otel_runtime.start_as_current_span(f"sut.{sut_name}") as span:
                span.set_attribute("rue.sut", True)
                span.set_attribute("rue.sut.name", sut_name)
                _set_input_attrs(span, args, kwargs)
                result = await fn(*args, **kwargs)
                _set_output_attrs(span, result)
                return result

        return traced_async

    @functools.wraps(fn)
    def traced(*args: Any, **kwargs: Any) -> Any:
        tracer = get_test_tracer()
        if tracer is None or tracer.otel_trace_session is None:
            return fn(*args, **kwargs)

        with otel_runtime.start_as_current_span(f"sut.{sut_name}") as span:
            span.set_attribute("rue.sut", True)
            span.set_attribute("rue.sut.name", sut_name)
            _set_input_attrs(span, args, kwargs)
            result = fn(*args, **kwargs)
            _set_output_attrs(span, result)
            return result

    return traced


def _trace_instance_method(instance: Any, *, sut_name: str, method: str) -> Any:
    original_method = getattr(instance, method)

    if inspect.iscoroutinefunction(original_method):

        @functools.wraps(original_method)
        async def traced_async(*args: Any, **kwargs: Any) -> Any:
            tracer = get_test_tracer()
            if tracer is None or tracer.otel_trace_session is None:
                return await original_method(*args, **kwargs)

            with otel_runtime.start_as_current_span(f"sut.{sut_name}") as span:
                span.set_attribute("rue.sut", True)
                span.set_attribute("rue.sut.name", sut_name)
                _set_input_attrs(span, args, kwargs)
                result = await original_method(*args, **kwargs)
                _set_output_attrs(span, result)
                return result

        setattr(instance, method, traced_async)
        return instance

    @functools.wraps(original_method)
    def traced(*args: Any, **kwargs: Any) -> Any:
        tracer = get_test_tracer()
        if tracer is None or tracer.otel_trace_session is None:
            return original_method(*args, **kwargs)

        with otel_runtime.start_as_current_span(f"sut.{sut_name}") as span:
            span.set_attribute("rue.sut", True)
            span.set_attribute("rue.sut.name", sut_name)
            _set_input_attrs(span, args, kwargs)
            result = original_method(*args, **kwargs)
            _set_output_attrs(span, result)
            return result

    setattr(instance, method, traced)
    return instance


# Trace helpers


def _set_input_attrs(span: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    """Set input attributes on span, respecting trace content settings."""
    tracer = get_test_tracer()
    if tracer is None or tracer.otel_trace_session is None or not tracer.otel_content:
        span.set_attribute("sut.input.count", len(args) + len(kwargs))
        return

    if args:
        span.set_attribute("sut.input.args", repr(args))
    if kwargs:
        span.set_attribute("sut.input.kwargs", repr(kwargs))


def _set_output_attrs(span: Any, result: Any) -> None:
    """Set output attributes on span, respecting trace content settings."""
    tracer = get_test_tracer()
    if tracer is None or tracer.otel_trace_session is None or not tracer.otel_content:
        span.set_attribute("sut.output.type", type(result).__name__)
        return

    span.set_attribute("sut.output", repr(result))
