"""Metric abstractions for the Rue testing framework.

This module provides the core classes for recording, computing, and managing
metrics during test execution.
"""

from __future__ import annotations

import math
import statistics
import threading
import warnings
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import validate_call

from rue.context.collectors import CURRENT_METRIC_RESULTS
from rue.models import Locator, Spec
from rue.resources.models import ResourceSpec, Scope


if TYPE_CHECKING:
    from rue.assertions.base import AssertionResult


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
class MetricState:
    """Typed cache for computed metric values to avoid redundant calculations.

    Attributes:
    ----------
    len : int, optional
        Number of recorded values.
    sum : float, optional
        Sum of all recorded values.
    min : float, optional
        Minimum value among recorded values.
    max : float, optional
        Maximum value among recorded values.
    median : float, optional
        Median of the recorded values.
    mean : float, optional
        Arithmetic mean of the recorded values.
    variance : float, optional
        Sample variance of the recorded values.
    std : float, optional
        Sample standard deviation of the recorded values.
    pvariance : float, optional
        Population variance of the recorded values.
    pstd : float, optional
        Population standard deviation of the recorded values.
    ci_90 : tuple of (float, float), optional
        90% confidence interval (lower, upper).
    ci_95 : tuple of (float, float), optional
        95% confidence interval (lower, upper).
    ci_99 : tuple of (float, float), optional
        99% confidence interval (lower, upper).
    percentiles : list of float, optional
        List of 99 quantiles (p1 to p99) computed with n=100.
    counter : Counter, optional
        Frequency count of each unique raw value. Missing keys return 0.
    distribution : dict, optional
        Share of each unique raw value.
    """

    len: int | None = None
    sum: float | None = None
    min: float | None = None
    max: float | None = None
    median: float | None = None
    mean: float | None = None
    variance: float | None = None
    std: float | None = None
    pvariance: float | None = None
    pstd: float | None = None
    ci_90: tuple[float, float] | None = None
    ci_95: tuple[float, float] | None = None
    ci_99: tuple[float, float] | None = None
    percentiles: list[float] | None = None
    counter: Counter[int | float | bool] | None = None
    distribution: dict[int | float | bool, float] | None = None


@dataclass(slots=True)
class Metric:
    """Thread-safe class for recording data points and computing statistical metrics.

    This class maintains a list of raw values and provides properties to compute
    various statistics (mean, std, percentiles, etc.) on demand.

    Attributes:
    ----------
    metadata : MetricMetadata
        Metadata describing the collection context (including identity).
    """

    metadata: MetricMetadata = field(default_factory=MetricMetadata)

    _raw_values: list[int | float | bool] = field(
        default_factory=list, repr=False
    )
    _float_values: list[float] = field(default_factory=list, repr=False)
    _values_lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False
    )
    _cache: MetricState = field(default_factory=MetricState, repr=False)

    @property
    def _identity_name(self) -> str:
        return self.metadata.identity.locator.function_name or "unnamed metric"

    def _warn_not_enough_values(self, statistic: str) -> None:
        warnings.warn(
            f"Cannot compute {statistic} for {self._identity_name} - "
            "not enough values. Returning NaN.",
            stacklevel=2,
        )

    @validate_call
    def add_record(self, value: CalculatedValue) -> None:
        """Record one or more new data points.

        Parameters
        ----------
        value : int, float, bool, list of these, or tuple of these
            The value(s) to add to the metric.
        """
        with self._values_lock:
            if self.metadata.first_item_recorded_at is None:
                self.metadata.first_item_recorded_at = datetime.now(UTC)
            self.metadata.last_item_recorded_at = datetime.now(UTC)
            self._cache = MetricState()
            match value:
                case list() as values:
                    self._raw_values.extend(values)
                    self._float_values.extend(float(v) for v in values)

                case tuple() as values:
                    items: list[int | float | bool] = []
                    for v in values:
                        if isinstance(v, (int, float, bool)):
                            items.append(v)
                        else:
                            raise TypeError(
                                "add_record only supports scalar or "
                                "sequences of int|float|bool."
                            )
                    self._raw_values.extend(items)
                    self._float_values.extend(float(v) for v in items)

                case int() | float() | bool() as v:
                    self._raw_values.append(v)
                    self._float_values.append(float(v))

                case _:
                    raise TypeError(
                        "add_record only supports scalar or "
                        "sequences of int|float|bool."
                    )

    @property
    def raw_values(self) -> list[int | float | bool]:
        with self._values_lock:
            value = list(self._raw_values)
            return value

    @property
    def len(self) -> int:
        with self._values_lock:
            if self._cache.len is None:
                self._cache.len = len(self._raw_values)
            value = self._cache.len
            return value

    @property
    def sum(self) -> float:
        with self._values_lock:
            if self._cache.sum is None:
                self._cache.sum = math.fsum(self._float_values)
            value = self._cache.sum
            return value

    @property
    def min(self) -> float:
        with self._values_lock:
            if self._cache.min is None:
                if self.len == 0:
                    self._warn_not_enough_values("min")
                    self._cache.min = math.nan
                else:
                    self._cache.min = min(self._float_values)
            value = self._cache.min
            return value

    @property
    def max(self) -> float:
        with self._values_lock:
            if self._cache.max is None:
                if self.len == 0:
                    self._warn_not_enough_values("max")
                    value = math.nan
                    self._cache.max = value
                else:
                    self._cache.max = max(self._float_values)
            value = self._cache.max
            return value

    @property
    def median(self) -> float:
        with self._values_lock:
            if self._cache.median is None:
                if self.len == 0:
                    self._warn_not_enough_values("median")
                    self._cache.median = math.nan
                else:
                    self._cache.median = statistics.median(self._float_values)
            value = self._cache.median
            return value

    @property
    def mean(self) -> float:
        with self._values_lock:
            if self._cache.mean is None:
                if self.len == 0:
                    self._warn_not_enough_values("mean")
                    self._cache.mean = math.nan
                else:
                    self._cache.mean = statistics.mean(self._float_values)
            value = self._cache.mean
            return value

    @property
    def variance(self) -> float:
        with self._values_lock:
            if self._cache.variance is None:
                if self.len < 2:
                    self._warn_not_enough_values("variance")
                    self._cache.variance = math.nan
                else:
                    self._cache.variance = statistics.variance(
                        self._float_values, xbar=self.mean
                    )
            value = self._cache.variance
            return value

    @property
    def std(self) -> float:
        with self._values_lock:
            if self._cache.std is None:
                if self.len < 2:
                    self._warn_not_enough_values("std")
                    self._cache.std = math.nan
                else:
                    self._cache.std = statistics.stdev(
                        self._float_values, xbar=self.mean
                    )
            value = self._cache.std
            return value

    @property
    def pvariance(self) -> float:
        with self._values_lock:
            if self._cache.pvariance is None:
                if self.len == 0:
                    self._warn_not_enough_values("pvariance")
                    self._cache.pvariance = math.nan
                else:
                    self._cache.pvariance = statistics.pvariance(
                        self._float_values, mu=self.mean
                    )
            value = self._cache.pvariance
            return value

    @property
    def pstd(self) -> float:
        with self._values_lock:
            if self._cache.pstd is None:
                if self.len == 0:
                    self._warn_not_enough_values("pstd")
                    self._cache.pstd = math.nan
                else:
                    self._cache.pstd = statistics.pstdev(
                        self._float_values, mu=self.mean
                    )
            value = self._cache.pstd
            return value

    @property
    def ci_90(self) -> tuple[float, float]:
        with self._values_lock:
            if self._cache.ci_90 is None:
                if self.len == 0:
                    self._warn_not_enough_values("ci_90")
                    self._cache.ci_90 = (math.nan, math.nan)
                else:
                    half = 1.645 * self.std / math.sqrt(self.len)
                    self._cache.ci_90 = (self.mean - half, self.mean + half)
            value = self._cache.ci_90
            return value

    @property
    def ci_95(self) -> tuple[float, float]:
        with self._values_lock:
            if self._cache.ci_95 is None:
                if self.len == 0:
                    self._warn_not_enough_values("ci_95")
                    self._cache.ci_95 = (math.nan, math.nan)
                else:
                    half = 1.96 * self.std / math.sqrt(self.len)
                    self._cache.ci_95 = (self.mean - half, self.mean + half)
            value = self._cache.ci_95
            return value

    @property
    def ci_99(self) -> tuple[float, float]:
        with self._values_lock:
            if self._cache.ci_99 is None:
                if self.len == 0:
                    self._warn_not_enough_values("ci_99")
                    self._cache.ci_99 = (math.nan, math.nan)
                else:
                    half = 2.576 * self.std / math.sqrt(self.len)
                    self._cache.ci_99 = (self.mean - half, self.mean + half)
            value = self._cache.ci_99
            return value

    @property
    def percentiles(self) -> list[float]:
        with self._values_lock:
            if self._cache.percentiles is None:
                if self.len < 2:
                    warnings.warn(
                        f"Metric '{self._identity_name}' has less "
                        "than 2 values. Cannot compute percentiles.",
                        stacklevel=2,
                    )
                    self._cache.percentiles = [math.nan] * 99
                else:
                    self._cache.percentiles = statistics.quantiles(
                        self._float_values, n=100, method="inclusive"
                    )
            value = self._cache.percentiles
            return value

    @property
    def p25(self) -> float:
        with self._values_lock:
            value = self.percentiles[24]
            return value

    @property
    def p50(self) -> float:
        return self.median

    @property
    def p75(self) -> float:
        with self._values_lock:
            value = self.percentiles[74]
            return value

    @property
    def p90(self) -> float:
        with self._values_lock:
            value = self.percentiles[89]
            return value

    @property
    def p95(self) -> float:
        with self._values_lock:
            value = self.percentiles[94]
            return value

    @property
    def p99(self) -> float:
        with self._values_lock:
            value = self.percentiles[98]
            return value

    @property
    def counter(self) -> Counter[int | float | bool]:
        with self._values_lock:
            if self._cache.counter is None:
                self._cache.counter = Counter(self._raw_values)
            value = self._cache.counter
            return value

    @property
    def distribution(self) -> dict[int | float | bool, float]:
        with self._values_lock:
            if self._cache.distribution is None:
                total = self.len
                counts = self.counter
                self._cache.distribution = (
                    {k: v / total for k, v in counts.items()}
                    if total > 0
                    else {}
                )
            value = self._cache.distribution
            return value


@dataclass(slots=True)
class MetricResult:
    """Result of evaluating a `Metric` resource.

    Parameters
    ----------
    metadata : MetricMetadata
        Snapshot of metadata describing where/when the metric was recorded
        (identity, consumers, direct providers, timestamps).
    dependencies : list[ResourceSpec]
        Direct resource dependencies for the metric provider.
    assertion_results : list[AssertionResult]
        Assertion results collected while the metric resource was running.
    value : CalculatedValue
        The last yielded value from the metric generator. NaN if no value was yielded.
    """

    metadata: MetricMetadata
    assertion_results: list[AssertionResult]
    value: CalculatedValue
    dependencies: list[ResourceSpec] = field(default_factory=list)

    @property
    def primary_case_id(self) -> str:
        cases = sorted(
            str(case_id)
            for consumer in self.metadata.consumers
            if (case_id := getattr(consumer, "case_id", None)) is not None
        )
        if cases:
            return cases[0]
        suffixes = sorted(
            suffix
            for consumer in self.metadata.consumers
            if (suffix := getattr(consumer, "suffix", None))
        )
        if suffixes:
            return suffixes[0]
        return ""

    @property
    def has_failures(self) -> bool:
        return any(not assertion.passed for assertion in self.assertion_results)

    def __post_init__(self) -> None:
        if self.dependencies and not self.metadata.direct_providers:
            self.metadata.direct_providers = list(self.dependencies)
        if self.metadata.direct_providers and not self.dependencies:
            self.dependencies = list(self.metadata.direct_providers)
        collector = CURRENT_METRIC_RESULTS.get()
        if collector is not None:
            collector.append(self)
