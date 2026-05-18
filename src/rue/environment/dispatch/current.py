"""Context-local active-environment binding for dispatcher routing."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from rue.environment.runtime import Environment


_STACK: ContextVar[tuple[Environment, ...]] = ContextVar(
    "environment_stack", default=()
)


def activate(env: Environment) -> None:
    """Push `env` onto the per-context activation stack."""
    _STACK.set((*_STACK.get(), env))


def deactivate(env: Environment) -> None:
    """Pop `env` off the per-context activation stack."""
    stack = _STACK.get()
    if not stack:
        raise RuntimeError("No active Environment to deactivate.")
    if stack[-1] is not env:
        raise RuntimeError("Cannot deactivate Environment out of order.")
    _STACK.set(stack[:-1])


def active() -> Environment | None:
    """Return the innermost activated Environment in this context, or None."""
    stack = _STACK.get()
    return stack[-1] if stack else None


def install_dispatcher(
    owner: Any,
    name: str,
    routed: Callable[..., Any],
) -> None:
    """Wrap `owner.name` to route through `routed` when an env is active.

    `routed` is a plain function `(env, *args, **kwargs) -> Any` whose
    first arg is the active env; the "if env is None: passthrough"
    boilerplate lives only in this wrapper. Silently no-ops when
    `owner.name` is missing, so platform-conditional functions
    (`fchdir`, `getxattr`, …) can be registered unconditionally.
    """
    orig = getattr(owner, name, None)
    if orig is None:
        return

    @wraps(orig)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        env = active()
        if env is None:
            return orig(*args, **kwargs)
        return routed(env, *args, **kwargs)

    setattr(owner, name, wrapper)


__all__ = [
    "activate",
    "active",
    "deactivate",
    "install_dispatcher",
]
