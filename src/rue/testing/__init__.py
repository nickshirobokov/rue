"""Rue testing package — discovery, execution, and decorators."""

from ..resources import resource
from .decorators import backend, iterate, tag, test
from .execution.backend import ExecutionBackend
from .models import (
    Case,
    CaseFactory,
    CaseGroup,
    ExecutedRun,
    ExecutedTest,
    LoadedTestDef,
    RunContext,
    TestStatus,
)
from .outcomes import fail, skip, xfail
from .runner import Runner


__all__ = [
    "Case",
    "CaseFactory",
    "CaseGroup",
    "ExecutedRun",
    "ExecutedTest",
    "ExecutionBackend",
    "LoadedTestDef",
    "RunContext",
    "Runner",
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
