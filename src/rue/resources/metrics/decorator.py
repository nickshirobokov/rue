from __future__ import annotations

import functools
import inspect
import math
from collections.abc import AsyncGenerator, Callable, Generator
from dataclasses import replace
from typing import Any, ParamSpec

from rue.context.collectors import CURRENT_ASSERTION_RESULTS
from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_RESOURCE_CONSUMER_KIND,
    CURRENT_RESOURCE_PROVIDER,
    CURRENT_RESOURCE_RESOLVER,
    bind,
)
from rue.resources.models import ResourceIdentity, Scope
from rue.resources.registry import resource

from .base import CalculatedValue, Metric, MetricResult


P = ParamSpec("P")


def metric(
    fn: Callable[P, Generator[Metric | CalculatedValue, Any, Any]]
    | Callable[P, AsyncGenerator[Metric | CalculatedValue, Any]]
    | None = None,
    *,
    scope: Scope | str = Scope.SESSION,
) -> Any:
    """Register a metric resource and capture its final result.

    This decorator wraps a **generator** or **async generator** function into a
    managed resource via `rue.resources.resource`. The wrapped function
    must:

    - `yield` a single `Metric` instance first (this is what gets injected and
      used during the test run).
    - Optionally `yield` a **final value** (int/float/bool/list/CI tuple) later.
      When the generator completes, a `MetricResult` is emitted containing that
      final value and any assertions evaluated while the generator was running.

    Parameters
    ----------
    fn : callable, optional
        The generator/async-generator function to register. If None, returns a
        decorator.
    scope : Scope or str, default Scope.SESSION
        The lifecycle scope of the metric resource. Can be "case", "suite",
        or "session".
    """
    if fn is None:
        return lambda f: metric(f, scope=scope)

    name = fn.__name__

    is_generator = inspect.isgeneratorfunction(fn)
    is_async_generator = inspect.isasyncgenfunction(fn)

    def on_resolve_hook(m: Metric) -> Metric:
        scope_val = scope if isinstance(scope, Scope) else Scope(scope)
        ident = m.metadata.identity
        m.metadata.identity = ResourceIdentity(
            name=name,
            scope=scope_val,
            provider_path=ident.provider_path,
            provider_dir=ident.provider_dir,
        )
        return m

    def on_injection_hook(m: Metric) -> Metric:
        consumer_name = CURRENT_RESOURCE_CONSUMER.get()
        if (
            consumer_name
            and CURRENT_RESOURCE_CONSUMER_KIND.get() == "resource"
        ):
            m.metadata.collected_from_resources.add(consumer_name)
        return m

    if is_generator:

        @functools.wraps(fn)
        def wrapped_gen(
            *args: Any, **kwargs: Any
        ) -> Generator[Metric, Any, Any]:
            assertions_results = []

            with bind(CURRENT_ASSERTION_RESULTS, assertions_results):
                gen = fn(*args, **kwargs)
                metric_instance: Metric = next(gen)

            yield metric_instance

            with bind(CURRENT_ASSERTION_RESULTS, assertions_results):
                final_value = None
                while True:
                    try:
                        final_value = next(gen)
                    except StopIteration:
                        if final_value is None:
                            value = math.nan
                        else:
                            value = final_value
                        provider = CURRENT_RESOURCE_PROVIDER.get()
                        resolver = CURRENT_RESOURCE_RESOLVER.get()
                        metadata = replace(metric_instance.metadata)
                        if provider is not None:
                            ident = metadata.identity
                            metadata = replace(
                                metadata,
                                identity=replace(
                                    ident,
                                    provider_path=provider.identity.provider_path,
                                    provider_dir=provider.identity.provider_dir,
                                ),
                            )
                        dependencies = (
                            resolver.direct_dependencies_for(
                                provider.identity
                            )
                            if provider is not None and resolver is not None
                            else []
                        )
                        MetricResult(
                            metadata=metadata,
                            dependencies=dependencies,
                            assertion_results=assertions_results,
                            value=value,
                        )
                        break

        return resource(
            wrapped_gen,
            scope=scope,
            on_resolve=on_resolve_hook,
            on_injection=on_injection_hook,
            origin_fn=fn,
        )

    if is_async_generator:

        @functools.wraps(fn)
        async def wrapped_async_gen(*args: Any, **kwargs: Any):
            assertions_results = []

            with bind(CURRENT_ASSERTION_RESULTS, assertions_results):
                gen = fn(*args, **kwargs)
                metric_instance: Metric = await gen.__anext__()

            yield metric_instance

            with bind(CURRENT_ASSERTION_RESULTS, assertions_results):
                final_value = None
                while True:
                    try:
                        final_value = await gen.__anext__()
                    except StopAsyncIteration:
                        if final_value is None:
                            value = math.nan
                        else:
                            value = final_value
                        provider = CURRENT_RESOURCE_PROVIDER.get()
                        resolver = CURRENT_RESOURCE_RESOLVER.get()
                        metadata = replace(metric_instance.metadata)
                        if provider is not None:
                            ident = metadata.identity
                            metadata = replace(
                                metadata,
                                identity=replace(
                                    ident,
                                    provider_path=provider.identity.provider_path,
                                    provider_dir=provider.identity.provider_dir,
                                ),
                            )
                        dependencies = (
                            resolver.direct_dependencies_for(
                                provider.identity
                            )
                            if provider is not None and resolver is not None
                            else []
                        )
                        MetricResult(
                            metadata=metadata,
                            dependencies=dependencies,
                            assertion_results=assertions_results,
                            value=value,
                        )
                        break

        return resource(
            wrapped_async_gen,
            scope=scope,
            on_resolve=on_resolve_hook,
            on_injection=on_injection_hook,
            origin_fn=fn,
        )

    msg = f"""
        {fn.__name__} is not a generator or async generator and can't be wrapped as a Rue metric.
        To fix: yield a Metric instance and optionally yield a final calculated value.
        """
    raise ValueError(msg)
