"""Metrics module for aggregating predicate results."""

from rue.resources.metrics.metric import Metric

from .decorator import metric
from .scope import metrics


__all__ = ["Metric", "metric", "metrics"]
