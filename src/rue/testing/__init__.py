"""Rue testing package — discovery, execution, and decorators."""

from rue.context.runtime import SuiteContext

from ..resources import resource
from .decorators import backend, iterate, tag, test
from .execution.backend import ExecutionBackend
from .execution.case import Case, CaseFactory, CaseGroup, EdgeCaseFactory
from .execution.models import ExecutedTest, LoadedTestDef, TestStatus
from .execution.suite.executable import ExecutableSuite
from .execution.suite.models import ExecutedSuite
from .outcomes import fail, skip, xfail


__all__ = [
    "Case",
    "CaseFactory",
    "CaseGroup",
    "EdgeCaseFactory",
    "ExecutableSuite",
    "ExecutedSuite",
    "ExecutedTest",
    "ExecutionBackend",
    "LoadedTestDef",
    "SuiteContext",
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
