"""Rue - Testing framework for AI agents."""

from .predicates import PredicateResult, predicate
from .reports import Reporter
from .resources.metrics import Metric, metric, metrics
from .resources.sut import SUT, sut
from .testing import (
    Case,
    CaseGroup,
    fail,
    resource,
    skip,
    test,
    xfail,
    iterate,
    tag,
)
from .telemetry import OtelTraceSession

resource.sut = sut
resource.metric = metric
test.iterate = iterate
test.tag = tag

__all__ = [
    # Core testing
    "Case",
    "CaseGroup",
    "resource",
    "test",
    "iterate",
    "tag",
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
