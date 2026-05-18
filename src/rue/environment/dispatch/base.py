"""Shared dispatcher installation primitive."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from rue.environment.env import Environment


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
    (`fchdir`, `getxattr`, ...) can be registered unconditionally.
    """
    orig = getattr(owner, name, None)
    if orig is None:
        return

    @wraps(orig)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        env = Environment.current()
        if env is None:
            return orig(*args, **kwargs)
        return routed(env, *args, **kwargs)

    setattr(owner, name, wrapper)


__all__ = ["install_dispatcher"]
