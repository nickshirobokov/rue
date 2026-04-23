"""Backend decorator for selecting test execution strategy."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from rue.testing.execution.base import ExecutionBackend
from rue.testing.models import BackendModifier


F = TypeVar("F", bound=Callable[..., Any])


def backend(spec: str | ExecutionBackend) -> Callable[[F], F]:
    """Select the execution backend (string or :class:`ExecutionBackend`)."""
    chosen = spec if type(spec) is ExecutionBackend else ExecutionBackend(spec)

    def decorator(target: F) -> F:
        modifiers: list[Any] = getattr(target, "__rue_modifiers__", [])
        existing = any(
            isinstance(modifier, BackendModifier) for modifier in modifiers
        )
        if existing:
            if getattr(target, "__rue_definition_error__", None) is None:
                target.__rue_definition_error__ = "Multiple @rue.test.backend(...) decorators are not supported."  # type: ignore[attr-defined]
        else:
            modifiers.append(BackendModifier(backend=chosen))
        target.__rue_modifiers__ = modifiers  # type: ignore[attr-defined]
        target.__rue_test__ = True  # type: ignore[attr-defined]
        return target

    return decorator


__all__ = ["backend"]
