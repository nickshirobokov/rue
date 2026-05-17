"""Context-routed dispatchers that virtualize cwd / env vars per `Environment`."""

from __future__ import annotations

from rue.environment.dispatch.current import (
    _CURRENT_ENVIRONMENT,
    _ENVIRONMENT_TOKENS,
    current,
)
from rue.environment.dispatch.environ import (
    install_environ_dispatchers,
    real_environ,
    real_environb,
)
from rue.environment.dispatch.paths import install_path_dispatchers


_INSTALLED = False


def install_dispatchers() -> None:
    """Install all chokepoint dispatchers. Idempotent."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    install_environ_dispatchers()
    install_path_dispatchers()


__all__ = [
    "_CURRENT_ENVIRONMENT",
    "_ENVIRONMENT_TOKENS",
    "current",
    "install_dispatchers",
    "real_environ",
    "real_environb",
]
