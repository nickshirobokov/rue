"""Context-local active-environment binding for dispatcher routing."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from rue.environment.runtime import Environment


_CURRENT_ENVIRONMENT: ContextVar["Environment | None"] = ContextVar(
    "current_environment", default=None
)
_ENVIRONMENT_TOKENS: ContextVar[
    tuple[Token["Environment | None"], ...]
] = ContextVar("environment_tokens", default=())


def current() -> "Environment | None":
    """Return the Environment active in this context, or None."""
    return _CURRENT_ENVIRONMENT.get()


__all__ = [
    "_CURRENT_ENVIRONMENT",
    "_ENVIRONMENT_TOKENS",
    "current",
]
