"""Rue testing package — discovery, execution, and decorators."""

from ..resources import resource
from .decorators import backend, iterate, tag, test
from .execution.backend import ExecutionBackend
from .execution.queue import QueueBatch, RunnerStep, SessionQueue
from .models import (
    Case,
    CaseGroup,
    ExecutedTest,
    LoadedTestDef,
    ExecutedRun,
    RunContext,
    TestStatus,
)
from .outcomes import fail, skip, xfail
from .runner import Runner


__all__ = [
    "Case",
    "CaseGroup",
    "ExecutedTest",
    "ExecutionBackend",
    "LoadedTestDef",
    "QueueBatch",
    "ExecutedRun",
    "RunContext",
    "Runner",
    "RunnerStep",
    "SessionQueue",
    "TestStatus",
    "backend",
    "fail",
    "iterate",
    "resource",
    "skip",
    "tag",
    "test",
    "xfail",
]
