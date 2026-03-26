"""Decorator for traced predicate functions."""

from asyncio import iscoroutinefunction
from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import BoundArguments, Parameter, signature
from typing import Any, Protocol, TypeVar, overload, ParamSpec, Concatenate

from rue.context.collectors import CURRENT_PREDICATE_RESULTS
from rue.context.runtime import CURRENT_TEST_TRACER
from rue.predicates.models import PredicateResult
from rue.telemetry.otel.runtime import otel_runtime

P = ParamSpec("P")
ACTUAL = TypeVar("ACTUAL", contravariant=True)
REFERENCE = TypeVar("REFERENCE", contravariant=True)


# Protocols for static type checking


class _SyncPredicateFn(Protocol[ACTUAL, REFERENCE, P]):
    """Sync callable requiring positional-or-keyword ``actual`` and ``reference``."""

    def __call__(
        self,
        actual: ACTUAL,
        reference: REFERENCE,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> bool | PredicateResult: ...


class _AsyncPredicateFn(Protocol[ACTUAL, REFERENCE, P]):
    """Async callable requiring positional-or-keyword ``actual`` and ``reference``."""

    def __call__(
        self,
        actual: ACTUAL,
        reference: REFERENCE,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> Awaitable[bool | PredicateResult]: ...


# Decorator implementation


@overload
def predicate(
    func: _AsyncPredicateFn[ACTUAL, REFERENCE, P], *, name: str | None = None
) -> Callable[Concatenate[ACTUAL, REFERENCE, P], Awaitable[bool]]: ...


@overload
def predicate(
    func: _SyncPredicateFn[ACTUAL, REFERENCE, P], *, name: str | None = None
) -> Callable[Concatenate[ACTUAL, REFERENCE, P], bool]: ...


@overload
def predicate(
    *, name: str | None = None
) -> Callable[
    [
        _AsyncPredicateFn[ACTUAL, REFERENCE, P]
        | _SyncPredicateFn[ACTUAL, REFERENCE, P]
    ],
    Callable[Concatenate[ACTUAL, REFERENCE, P], bool | Awaitable[bool]],
]: ...


def predicate(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
) -> Any:
    """Decorate a predicate function to record each outcome for test reports and
    for tracing. The wrapped function still returns a plain ``bool`` (or ``bool``
    from an async function).

    The parameters must be named ``actual`` and ``reference`` (not positional-only;
    you may pass them positionally or as keywords). The return type must be ``bool`` or
    :class:`~rue.predicates.models.PredicateResult`.

    Use ``name=`` to choose the label shown in reports and traces instead of the
    function's ``__name__``.

    Examples
    --------
    >>> @predicate
    ... def is_even(actual: int, reference: int) -> bool:
    ...     return actual % 2 == 0
    >>> assert is_even(1, 2)
    >>> @predicate
    ... def within_tolerance(
    ...     actual: float,
    ...     reference: float,
    ...     *,
    ...     tolerance: float = 0.1,
    ...     strict: bool = True,
    ...     confidence: float = 1.0,
    ... ) -> bool:
    ...     delta = abs(actual - reference)
    ...     if strict:
    ...         return delta <= tolerance
    ...     return delta <= 2 * tolerance
    >>> assert within_tolerance(
    ...     10.05,
    ...     10.0,
    ...     tolerance=0.01,
    ...     strict=False,
    ...     confidence=0.65,
    ... )
    """

    def decorate(f: Callable[..., Any]) -> Callable[..., Any]:
        predicate_name = (
            name if name is not None else getattr(f, "__name__", "<predicate>")
        )
        sig = signature(f)
        for param_name in ("actual", "reference"):
            param = sig.parameters.get(param_name)
            if param is None or param.kind is Parameter.POSITIONAL_ONLY:
                raise TypeError(
                    f"@predicate function '{predicate_name}' must declare named "
                    f"'actual' and 'reference' parameters. Got signature: {sig}"
                )
        span_name = f"predicate.{predicate_name}"

        if iscoroutinefunction(f):

            @wraps(f)
            async def async_wrapper(*args: Any, **kwargs: Any) -> bool:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                tracer = CURRENT_TEST_TRACER.get()
                if tracer is None or not tracer.has_otel_trace:
                    predicate_result = _normalize_result(
                        await f(*args, **kwargs),
                        predicate_name,
                        bound,
                    )
                    _record_result(predicate_result)
                    return predicate_result.value

                with otel_runtime.start_as_current_span(span_name) as span:
                    predicate_result = _normalize_result(
                        await f(*args, **kwargs),
                        predicate_name,
                        bound,
                    )
                    _record_result(predicate_result)
                    _set_trace_attributes(
                        span, predicate_name, predicate_result, bound
                    )
                    return predicate_result.value

            return async_wrapper

        @wraps(f)
        def sync_wrapper(*args: Any, **kwargs: Any) -> bool:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            tracer = CURRENT_TEST_TRACER.get()
            if tracer is None or not tracer.has_otel_trace:
                predicate_result = _normalize_result(
                    f(*args, **kwargs),
                    predicate_name,
                    bound,
                )
                _record_result(predicate_result)
                return predicate_result.value

            with otel_runtime.start_as_current_span(span_name) as span:
                predicate_result = _normalize_result(
                    f(*args, **kwargs),
                    predicate_name,
                    bound,
                )
                _record_result(predicate_result)
                _set_trace_attributes(
                    span, predicate_name, predicate_result, bound
                )
                return predicate_result.value

        return sync_wrapper

    if func is None:
        return decorate
    return decorate(func)


# Helpers


def _normalize_result(
    result: bool | PredicateResult,
    predicate_name: str,
    bound: BoundArguments,
) -> PredicateResult:
    match result:
        case PredicateResult():
            return result
        case bool():
            arguments = bound.arguments
            return PredicateResult(
                value=result,
                name=predicate_name,
                actual=str(arguments["actual"]),
                reference=str(arguments["reference"]),
                strict=arguments.get("strict", False),
                confidence=arguments.get("confidence", 1.0),
                message=arguments.get("message"),
            )
        case _:
            raise TypeError(
                f"@predicate function '{predicate_name}' returned an unexpected type: "
                f"{type(result).__name__}"
            )


def _record_result(result: PredicateResult) -> None:
    collector = CURRENT_PREDICATE_RESULTS.get()
    if collector is not None:
        collector.append(result)


def _set_trace_attributes(
    span: Any,
    predicate_name: str,
    result: PredicateResult,
    bound: BoundArguments,
) -> None:
    span.set_attribute("rue.predicate", True)
    span.set_attribute("rue.predicate.name", predicate_name)
    span.set_attribute("predicate.value", result.value)
    span.set_attribute("predicate.strict", result.strict)
    span.set_attribute("predicate.confidence", result.confidence)

    tracer = CURRENT_TEST_TRACER.get()
    if tracer is None or not tracer.records_otel_content:
        return

    span.set_attribute(
        "predicate.input.actual", repr(bound.arguments["actual"])
    )
    span.set_attribute(
        "predicate.input.reference", repr(bound.arguments["reference"])
    )
    if result.message is not None:
        span.set_attribute("predicate.message", repr(result.message))
