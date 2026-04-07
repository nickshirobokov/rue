"""System-Under-Test (SUT) decorator for traced test targets."""

import types
from collections.abc import Callable
from typing import Any

from rue.resources import Scope, resource
from rue.testing.sut.base import SUT


def sut(
    fn: Callable[..., Any] | None = None,
    *,
    scope: Scope | str = Scope.CASE,
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
            raise TypeError("@sut factories must return or yield a SUT.")

        sut_instance.name = factory_name
        return sut_instance

    return resource(
        fn,
        scope=scope,
        on_resolve=on_resolve,
    )
