"""Context-routed dispatchers for cwd and env vars per `Environment`."""

from __future__ import annotations

from rue.environment.dispatch.base import install_dispatcher
from rue.environment.dispatch.cwd import install_cwd_dispatchers
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
    install_cwd_dispatchers()
    install_path_dispatchers()


__all__ = [
    "install_dispatcher",
    "install_dispatchers",
    "real_environ",
    "real_environb",
]
