"""Rue testing package — discovery, execution, and decorators."""

from ..resources import resource
from .decorators import test
from .discovery import collect
from .models import (
    Case,
    CaseGroup,
    Run,
    TestDefinition,
    TestExecution,
    TestStatus,
)
from .outcomes import fail, skip, xfail
from .runner import Runner


__all__ = [
    "Case",
    "CaseGroup",
    "Run",
    "Runner",
    "TestDefinition",
    "TestExecution",
    "TestStatus",
    "collect",
    "fail",
    "resource",
    "skip",
    "test",
    "xfail",
]
