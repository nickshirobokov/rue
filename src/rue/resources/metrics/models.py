"""Metric data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from rue.context.collectors import CURRENT_METRIC_RESULTS
from rue.context.scopes import Scope
from rue.models import Locator, Spec
from rue.resources.models import ResourceSpec


if TYPE_CHECKING:
    from rue.assertions.models import AssertionResult


CalculatedValue = (
    int
    | float
    | bool
    | list[int | float | bool]
    | tuple[int | float | bool, ...]
    | tuple[tuple[int | float | bool, int], ...]
    | tuple[tuple[int | float | bool, float], ...]
    | tuple[float, float]
    | tuple[float, float, float]
)


@dataclass
class MetricMetadata:
    """Metadata for a metric tracking its lifecycle and origin.

    Attributes:
    ----------
    last_item_recorded_at : datetime, optional
        Timestamp of the most recently recorded value.
    first_item_recorded_at : datetime, optional
        Timestamp of the first recorded value.
    identity : ResourceSpec
        Name, scope, and provider origin for the metric.
    consumers : list of Spec
        Specs that consumed this metric through resource injection.
    direct_providers : list of ResourceSpec
        Resource providers directly used by this metric provider.
    """

    last_item_recorded_at: datetime | None = None
    first_item_recorded_at: datetime | None = None
    identity: ResourceSpec = field(
        default_factory=lambda: ResourceSpec(
            locator=Locator(module_path=None, function_name=""),
            scope=Scope.RUN,
        )
    )
    consumers: list[Spec] = field(default_factory=list)
    direct_providers: list[ResourceSpec] = field(default_factory=list)


@dataclass(slots=True)
class MetricResult:
    """Result of evaluating a `Metric` resource.

    Parameters
    ----------
    metadata : MetricMetadata
        Snapshot of metadata describing where/when the metric was recorded
        (identity, consumers, direct providers, timestamps).
    assertion_results : list[AssertionResult]
        Assertion results collected while the metric resource was running.
    value : CalculatedValue
        Last yielded value from the metric generator.
        NaN if no value was yielded.
    """

    metadata: MetricMetadata
    assertion_results: list[AssertionResult]
    value: CalculatedValue

    @property
    def primary_case_id(self) -> str:
        """Return the first case-like consumer identifier."""
        cases = sorted(
            str(case_id)
            for consumer in self.metadata.consumers
            if (case_id := getattr(consumer, "case_id", None)) is not None
        )
        if cases:
            return cases[0]
        suffixes = sorted(
            str(suffix)
            for consumer in self.metadata.consumers
            if (suffix := getattr(consumer, "suffix", None))
        )
        if suffixes:
            return suffixes[0]
        return ""

    @property
    def has_failures(self) -> bool:
        """Return whether any metric assertion failed."""
        return any(
            not assertion.passed for assertion in self.assertion_results
        )

    def __post_init__(self) -> None:
        """Attach new metric results to the active collector."""
        collector = CURRENT_METRIC_RESULTS.get()
        if collector is not None:
            collector.append(self)
