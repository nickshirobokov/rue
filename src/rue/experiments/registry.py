"""Experiment registration APIs."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from rue.experiments.models import ExperimentSpec
from rue.models import Locator

_EXPERIMENT_RECEIVER = frozenset({"self", "cls"})


P = ParamSpec("P")
T = TypeVar("T")


class ExperimentRegistry:
    """Registry of experiment hook declarations."""

    def __init__(self) -> None:
        self._experiments: dict[str, ExperimentSpec] = {}

    def experiment(
        self,
        values: Iterable[Any],
        *,
        ids: Sequence[str] | None = None,
    ) -> Callable[[Callable[P, T]], Callable[P, T]]:
        """Register a function as an experiment hook."""
        values_tuple = tuple(values)
        if not values_tuple:
            raise ValueError("experiment() requires at least one value")

        ids_tuple = (
            tuple(str(item) for item in ids)
            if ids is not None
            else tuple(repr(value) for value in values_tuple)
        )
        if len(ids_tuple) != len(values_tuple):
            raise ValueError("experiment() ids must match number of values")

        def decorator(fn: Callable[P, T]) -> Callable[P, T]:
            if inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
                raise ValueError("experiment hooks cannot be generators")

            signature = inspect.signature(fn)
            if "value" not in signature.parameters:
                raise ValueError("experiment hooks must accept a value parameter")

            filename = fn.__code__.co_filename
            path = (
                None
                if filename.startswith("<") and filename.endswith(">")
                else Path(filename).resolve()
            )

            spec = ExperimentSpec(
                locator=Locator(module_path=path, function_name=fn.__name__),
                values=values_tuple,
                ids=ids_tuple,
                fn=fn,
                dependencies=tuple(
                    p
                    for p in signature.parameters
                    if p not in _EXPERIMENT_RECEIVER and p != "value"
                ),
            )
            name = spec.locator.function_name
            if name in self._experiments:
                raise ValueError(f"Duplicate experiment: {name}")
            self._experiments[name] = spec
            return fn

        return decorator

    def all(self) -> tuple[ExperimentSpec, ...]:
        """Return registered experiments in import order."""
        return tuple(self._experiments.values())

    def reset(self) -> None:
        """Remove all registered experiments."""
        self._experiments.clear()


registry = ExperimentRegistry()


__all__ = ["ExperimentRegistry", "registry"]
