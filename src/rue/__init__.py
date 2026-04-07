"""Rue - Testing framework for AI agents."""

from .predicates import PredicateResult, predicate
from .reports import Reporter
from .resources.metrics import Metric, metric, metrics
from .resources.sut import SUT, sut
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
from .telemetry import OtelTraceSession

resource.sut = sut
resource.metric = metric

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
    "SUT",
    # Predicates
    "predicate",
    "PredicateResult",
    # Metrics
    "Metric",
    "metrics",
    # Reporters
    "Reporter",
    # OpenTelemetry
    "OtelTraceSession",
]
