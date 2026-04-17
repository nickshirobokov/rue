"""Backend decorator for selecting test execution strategy."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from rue.testing.execution.types import ExecutionBackend
from rue.testing.models import BackendModifier


F = TypeVar("F", bound=Callable[..., Any])


def backend(spec: str | ExecutionBackend) -> Callable[[F], F]:
    """Select the execution backend (string or :class:`ExecutionBackend`)."""

    chosen = (
        spec if type(spec) is ExecutionBackend else ExecutionBackend(spec)
    )
    modifier = BackendModifier(backend=chosen)

    def decorator(target: F) -> F:
        modifiers: list[Any] = getattr(target, "__rue_modifiers__", [])
        modifiers.append(modifier)
        target.__rue_modifiers__ = modifiers  # type: ignore[attr-defined]
        target.__rue_test__ = True  # type: ignore[attr-defined]
        return target

    return decorator


__all__ = ["backend"]
