"""Experiment model types."""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import product
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from rue.context.runtime import ResourceTransactionContext
from rue.models import Spec
from rue.resources import MonkeyPatch, Scope


if TYPE_CHECKING:
    from rue.resources.metrics.base import MetricResult
    from rue.resources.resolver import ResourceResolver
    from rue.testing.models import Run


_RECEIVER_PARAMETER_NAMES = {"self", "cls"}


@dataclass(slots=True)
class ExperimentSpec(Spec):
    """Registered experiment dimension and live hook."""

    values: tuple[Any, ...] = field(repr=False, compare=False)
    ids: tuple[str, ...]
    fn: Callable[..., Any] = field(repr=False, compare=False)
    dependencies: tuple[str, ...] = field(default=(), compare=False)

    async def apply(
        self,
        value_index: int,
        *,
        resolver: ResourceResolver,
        graph_key: UUID,
    ) -> None:
        """Apply this experiment hook to the current run process."""
        kwargs: dict[str, Any] = {"value": self.values[value_index]}
        kwargs.update(
            await resolver.resolve_graph_deps(
                graph_key,
                {},
                consumer_spec=self,
            )
        )
        if "monkeypatch" in self.dependencies:
            kwargs["monkeypatch"] = MonkeyPatch(
                lifetime=resolver.patch_lifetime(
                    Scope.RUN,
                ),
            )

        with ResourceTransactionContext(
            consumer_spec=self,
            provider_spec=self,
            resolver=resolver,
        ):
            result = self.fn(**kwargs)
            if inspect.isawaitable(result):
                await result


@dataclass(frozen=True, slots=True)
class ExperimentVariant:
    """One baseline or concrete experiment value combination."""

    index: int
    values: tuple[tuple[str, int, str], ...] = ()

    @classmethod
    def build_all(
        cls, experiments: tuple[ExperimentSpec, ...]
    ) -> tuple[ExperimentVariant, ...]:
        """Build baseline plus every cartesian value combination."""
        variants = [cls(index=0)]
        ranges = [range(len(experiment.values)) for experiment in experiments]
        for index, combination in enumerate(product(*ranges), start=1):
            variants.append(
                cls(
                    index=index,
                    values=tuple(
                        (
                            experiment.locator.function_name,
                            value_index,
                            experiment.ids[value_index],
                        )
                        for experiment, value_index in zip(
                            experiments, combination, strict=True
                        )
                    ),
                )
            )
        return tuple(variants)

    async def apply(
        self,
        experiments: tuple[ExperimentSpec, ...],
        *,
        resolver: ResourceResolver,
    ) -> None:
        """Apply this variant's selected experiment hooks."""
        definitions = {
            experiment.locator.function_name: experiment
            for experiment in experiments
        }
        keys_by_name = {
            name: uuid4() for name, _value_index, _value_id in self.values
        }
        resolver.registry.compile_di_graph(
            {
                keys_by_name[name]: (
                    definitions[name],
                    tuple(
                        dependency
                        for dependency in definitions[name].dependencies
                        if dependency != "monkeypatch"
                    ),
                )
                for name, _value_index, _value_id in self.values
            }
        )
        for name, value_index, _value_id in self.values:
            await definitions[name].apply(
                value_index,
                resolver=resolver,
                graph_key=keys_by_name[name],
            )

    @property
    def is_baseline(self) -> bool:
        """Return whether this variant has no experiment selections."""
        return not self.values

    @property
    def selection_indices(self) -> dict[str, int]:
        """Return selected value indices keyed by experiment name."""
        return {
            name: value_index
            for name, value_index, _value_id in self.values
        }

    @property
    def label(self) -> str:
        """Return a compact display label."""
        if self.is_baseline:
            return "baseline"
        return ", ".join(
            f"{name}={value_id}"
            for name, _value_index, value_id in self.values
        )


@dataclass(frozen=True, slots=True)
class ExperimentVariantResult:
    """Serializable summary of one variant run."""

    variant: ExperimentVariant
    run_id: UUID
    passed: int
    failed: int
    errors: int
    skipped: int
    xfailed: int
    xpassed: int
    total: int
    total_duration_ms: float
    stopped_early: bool
    metric_values: tuple[tuple[str, str], ...] = ()
    failures: tuple[tuple[str, str, str | None, str | None], ...] = ()

    @classmethod
    def build(
        cls,
        *,
        variant: ExperimentVariant,
        run: Run,
    ) -> ExperimentVariantResult:
        """Build a serializable result summary from a Rue run."""
        failures: list[tuple[str, str, str | None, str | None]] = []
        stack = list(run.result.executions)
        while stack:
            execution = stack.pop()
            if execution.status.is_failure:
                failures.append(
                    (
                        execution.label,
                        execution.status.value,
                        str(execution.execution_id),
                        None
                        if execution.result.error is None
                        else str(execution.result.error),
                    )
                )
            stack.extend(execution.sub_executions)

        return cls(
            variant=variant,
            run_id=run.run_id,
            passed=run.result.passed,
            failed=run.result.failed,
            errors=run.result.errors,
            skipped=run.result.skipped,
            xfailed=run.result.xfailed,
            xpassed=run.result.xpassed,
            total=run.result.total,
            total_duration_ms=run.result.total_duration_ms,
            stopped_early=run.result.stopped_early,
            metric_values=tuple(
                cls._metric_value(metric)
                for metric in run.result.metric_results
            ),
            failures=tuple(failures),
        )

    @property
    def pass_rate(self) -> float:
        """Return passed / total for ranking and display."""
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def rank_key(self) -> tuple[float, int]:
        """Return the pass-rate-only sort key with stable tie ordering."""
        return (self.pass_rate, -self.variant.index)

    @staticmethod
    def _metric_value(metric: MetricResult) -> tuple[str, str]:
        value = metric.value
        if isinstance(value, float) and math.isnan(value):
            value_str = "N/A"
        else:
            value_str = str(value)
        name = metric.metadata.identity.locator.function_name
        return (name, value_str)
