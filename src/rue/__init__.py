"""Rue - Testing framework for AI agents."""

from .predicates import PredicateResult, predicate
from .patching import MonkeyPatch
from .reports import Reporter
from .resources.metrics import Metric, metric, metrics
from .resources.sut import (
    CapturedEvent,
    CapturedOutput,
    CapturedStream,
    SUT,
    sut,
)
from .testing import (
    Case,
    CaseGroup,
    ExecutionBackend,
    QueueBatch,
    RunnerStep,
    SessionQueue,
    backend,
    fail,
    resource,
    skip,
    test,
    xfail,
    iterate,
    tag,
)

resource.sut = sut
resource.metric = metric
test.iterate = iterate
test.tag = tag
test.backend = backend

__all__ = [
    # Core testing
    "Case",
    "CaseGroup",
    "ExecutionBackend",
    "QueueBatch",
    "RunnerStep",
    "SessionQueue",
    "backend",
    "resource",
    "test",
    "iterate",
    "tag",
    "skip",
    "fail",
    "xfail",
    "SUT",
    "CapturedEvent",
    "CapturedOutput",
    "CapturedStream",
    "MonkeyPatch",
    # Predicates
    "predicate",
    "PredicateResult",
    # Metrics
    "Metric",
    "metrics",
    # Reporters
    "Reporter",
]
