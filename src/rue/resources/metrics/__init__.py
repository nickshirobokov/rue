"""Metrics module for aggregating predicate results."""

from .base import Metric, metric
from .scope import metrics


__all__ = ["Metric", "metric", "metrics"]
