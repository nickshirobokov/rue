"""Experiment decorator API."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, ParamSpec, TypeVar

from rue.resources import registry


P = ParamSpec("P")
T = TypeVar("T")


def experiment(
    values: Iterable[Any],
    *,
    ids: Sequence[str] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Register a run-scoped experiment hook."""
    return registry.experiment(values, ids=ids)


__all__ = ["experiment"]
