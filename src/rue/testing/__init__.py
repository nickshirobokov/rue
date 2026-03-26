"""Rue testing package — discovery, execution, and decorators."""

from ..resources import resource
from .decorators import (
    iter_case_groups,
    iter_cases,
    parametrize,
    repeat,
    run_inline,
    tag,
)
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
    "iter_case_groups",
    "iter_cases",
    "parametrize",
    "repeat",
    "resource",
    "run_inline",
    "skip",
    "tag",
    "xfail",
]
