from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from rue.assertions.base import AssertionResult
    from rue.resources.metrics.base import MetricResult
    from rue.predicates.models import PredicateResult


CURRENT_ASSERTION_RESULTS: ContextVar[list[AssertionResult] | None] = (
    ContextVar("current_assertion_results", default=None)
)
CURRENT_PREDICATE_RESULTS: ContextVar[list[PredicateResult] | None] = (
    ContextVar("current_predicate_results", default=None)
)
CURRENT_METRIC_RESULTS: ContextVar[list[MetricResult] | None] = ContextVar(
    "current_metric_results", default=None
)
