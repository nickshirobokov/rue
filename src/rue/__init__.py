"""Rue - Testing framework for AI agents."""

from .events import RunEventsProcessor, RunEventsReceiver
from .experiments.decorator import experiment
from .patching import MonkeyPatch
from .predicates import PredicateResult, predicate
from .resources.metrics import Metric, metric, metrics
from .resources.sut import (
    SUT,
    CapturedEvent,
    CapturedOutput,
    CapturedStream,
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
    iterate,
    resource,
    skip,
    tag,
    test,
    xfail,
)


resource.sut = sut
resource.metric = metric
test.iterate = iterate
test.tag = tag
test.backend = backend

__all__ = [
    "SUT",
    "CapturedEvent",
    "CapturedOutput",
    "CapturedStream",
    "Case",
    "CaseGroup",
    "ExecutionBackend",
    "Metric",
    "MonkeyPatch",
    "PredicateResult",
    "QueueBatch",
    "RunEventsProcessor",
    "RunEventsReceiver",
    "RunnerStep",
    "SessionQueue",
    "backend",
    "experiment",
    "fail",
    "iterate",
    "metrics",
    "predicate",
    "resource",
    "skip",
    "tag",
    "test",
    "xfail",
]
