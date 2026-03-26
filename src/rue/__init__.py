"""Rue - Testing framework for AI agents."""

from .metrics_ import Metric, metric
from .metrics_.scope import metrics
from .predicates import PredicateResult, predicate
from .reports import Reporter, reporter
from .testing import (
    Case,
    CaseGroup,
    fail,
    iter_case_groups,
    iter_cases,
    parametrize,
    repeat,
    resource,
    run_inline,
    skip,
    tag,
    xfail,
)
from .testing.sut import sut
from .telemetry import OtelTrace, OtelTraceSession, otel_span


__all__ = [
    # Core testing
    "Case",
    "CaseGroup",
    "iter_case_groups",
    "iter_cases",
    "parametrize",
    "repeat",
    "run_inline",
    "tag",
    "resource",
    "skip",
    "fail",
    "xfail",
    "sut",
    # Predicates
    "predicate",
    "PredicateResult",
    # Metrics
    "Metric",
    "metric",
    "metrics",
    # Reporters
    "Reporter",
    "reporter",
    # OpenTelemetry
    "otel_span",
    "OtelTrace",
    "OtelTraceSession",
]
