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

from pydantic import validate_call

from rue.resources.metrics.models import CalculatedValue, MetricMetadata


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
