"""Testing models - pure data classes."""

from rue.testing.models.definition import TestDefinition
from rue.testing.models.modifiers import (
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    Modifier,
    ParameterSet,
    ParamsIterateModifier,
)
from rue.testing.models.result import TestExecution, TestResult, TestStatus
from rue.testing.models.run import Run, RunEnvironment, RunResult
from rue.testing.models.case import Case, CaseGroup


# Backwards compatibility alias
TestItem = TestDefinition

__all__ = [
    "Case",
    "CaseGroup",
    "GroupsIterateModifier",
    "Run",
    "TestDefinition",
    "CasesIterateModifier",
    "IterateModifier",
    "Modifier",
    "ParameterSet",
    "ParamsIterateModifier",
    "RunEnvironment",
    "RunResult",
    "TestExecution",
    "TestItem",  # alias
    "TestResult",
    "TestStatus",
]
