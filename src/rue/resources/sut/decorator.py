"""System-Under-Test (SUT) decorator for traced test targets."""

import types
from collections.abc import Callable
from typing import Any

from rue.context.runtime import CURRENT_TEST, CURRENT_TEST_TRACER
from rue.resources.models import Scope
from rue.resources.registry import resource
from rue.resources.sut.base import SUT
from rue.telemetry.otel.backend import OtelTelemetryBackend


def sut(
    fn: Callable[..., Any] | None = None,
    *,
    scope: Scope | str = Scope.TEST,
) -> Any:
    """Register a SUT resource factory."""
    if fn is None:
        return lambda factory: sut(
            factory,
            scope=scope,
        )

    if not isinstance(fn, types.FunctionType):
        raise TypeError(f"""@sut can only decorate functions.
        Got: {type(fn).__name__}
        Expected: FunctionType
        """)

    factory_name = fn.__name__

    def on_resolve(sut_instance: Any) -> SUT:
        if not isinstance(sut_instance, SUT):
            error = TypeError("@sut factories must return or yield a SUT.")
            raise RuntimeError(error) from error

        sut_instance.name = factory_name
        return sut_instance

    def on_injection(sut_instance: SUT) -> SUT:
        test_ctx = CURRENT_TEST.get()
        execution_id = test_ctx.execution_id
        sut_instance.reset_output_state(execution_id)
        sut_instance.reset_trace_state(execution_id)
        tracer = CURRENT_TEST_TRACER.get()
        backend = (
            None
            if tracer is None
            else tracer.get_backend(OtelTelemetryBackend)
        )
        if backend is not None and backend.active_session is not None:
            sut_instance.activate_trace(backend.active_session)
        return sut_instance

    return resource(
        fn,
        scope=scope,
        on_resolve=on_resolve,
        on_injection=on_injection,
    )
