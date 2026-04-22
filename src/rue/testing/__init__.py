"""Rue testing package — discovery, execution, and decorators."""

from ..resources import resource
from .execution.types import ExecutionBackend
from .decorators import backend, iterate, tag, test
from .models import (
    Case,
    CaseGroup,
    Run,
    LoadedTestDef,
    ExecutedTest,
    TestStatus,
)
from .outcomes import fail, skip, xfail
from .queue import RunnerStep, TestQueue
from .runner import Runner


__all__ = [
    "Case",
    "CaseGroup",
    "Run",
    "Runner",
    "LoadedTestDef",
    "ExecutedTest",
    "TestStatus",
    "backend",
    "ExecutionBackend",
    "fail",
    "resource",
    "RunnerStep",
    "TestQueue",
    "skip",
    "iterate",
    "tag",
    "test",
    "xfail",
]
