"""Decorator for traced predicate functions."""

from asyncio import iscoroutinefunction
from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import BoundArguments, Parameter, signature
from typing import Any, Protocol, TypeVar, overload

from rue.context import PREDICATE_RESULTS_COLLECTOR
from rue.predicates.models import PredicateResult
from rue.tracing import get_tracer
from rue.tracing.attributes import is_trace_content_enabled, truncate_repr


# Protocols for static type checking

class _SyncPredicateFn(Protocol):
    """Sync callable requiring positional-or-keyword ``actual`` and ``reference``."""

    def __call__(self, actual: Any, reference: Any) -> bool | PredicateResult: ...


class _AsyncPredicateFn(Protocol):
    """Async callable requiring positional-or-keyword ``actual`` and ``reference``."""

    def __call__(self, actual: Any, reference: Any) -> Awaitable[bool | PredicateResult]: ...


_SyncF = TypeVar("_SyncF", bound=_SyncPredicateFn)
_AsyncF = TypeVar("_AsyncF", bound=_AsyncPredicateFn)


# Decorator implementation

@overload
def predicate(func: _AsyncF) -> _AsyncF: ...


@overload
def predicate(func: _SyncF) -> _SyncF: ...


def predicate(
    func: Callable[..., Any],
) -> Callable[..., Any]:
    """Decorate a predicate function so it records a :class:`PredicateResult`.

    In Rue, predicate evaluations inside ``assert`` statements can record
    :class:`~rue.predicates.models.PredicateResult` metadata into
    :class:`~rue.assertions.base.AssertionResult`. The decorated function still
    returns a boolean verdict. When tracing is enabled, each invocation also
    creates a ``predicate.<predicate_name>`` span with Rue predicate metadata.

    The decorated function must return a boolean or :class:`PredicateResult`,
    and must declare ``actual`` and ``reference`` as positional-or-keyword
    parameters. This constraint is enforced both statically (via the
    :class:`_SyncPredicateFn` / :class:`_AsyncPredicateFn` Protocol bounds)
    and at runtime. For boolean-returning predicates, Rue derives ``strict``,
    ``confidence``, and ``message`` metadata from the bound call, including
    the defaults declared on the predicate signature.

    Examples:
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
    predicate_name = getattr(func, "__name__", "<predicate>")
    sig = signature(func)
    for name in ("actual", "reference"):
        param = sig.parameters.get(name)
        if param is None or param.kind is Parameter.POSITIONAL_ONLY:
            raise TypeError(
                f"@predicate function '{predicate_name}' must declare named "
                f"'actual' and 'reference' parameters. Got signature: {sig}"
            )            
    span_name = f"predicate.{predicate_name}"

    if iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> bool:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            tracer = get_tracer()
            with tracer.start_as_current_span(span_name) as span:
                predicate_result = _normalize_result(
                    await func(*args, **kwargs),
                    predicate_name,
                    bound,
                )
                _record_result(predicate_result)
                _set_trace_attributes(span, predicate_name, predicate_result, bound)
                return predicate_result.value

        return async_wrapper

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> bool:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        tracer = get_tracer()
        with tracer.start_as_current_span(span_name) as span:
            predicate_result = _normalize_result(
                func(*args, **kwargs),
                predicate_name,
                bound,
            )
            _record_result(predicate_result)
            _set_trace_attributes(span, predicate_name, predicate_result, bound)
            return predicate_result.value

    return sync_wrapper


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
    collector = PREDICATE_RESULTS_COLLECTOR.get()
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

    if not is_trace_content_enabled():
        return

    span.set_attribute("predicate.input.actual", truncate_repr(bound.arguments["actual"]))
    span.set_attribute(
        "predicate.input.reference",
        truncate_repr(bound.arguments["reference"]),
    )
    if result.message is not None:
        span.set_attribute("predicate.message", truncate_repr(result.message))
