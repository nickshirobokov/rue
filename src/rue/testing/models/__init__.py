"""Testing models - pure data classes."""

from rue.testing.models.definition import TestDefinition, RueTestDefinition
from rue.testing.models.modifiers import (
    CaseGroupIterateModifier,
    CaseIterateModifier,
    Modifier,
    ParameterSet,
    ParametrizeModifier,
    RepeatModifier,
)
from rue.testing.models.result import TestExecution, TestResult, TestStatus
from rue.testing.models.run import Run, RunEnvironment, RunResult, RueRun
from rue.testing.models.case import Case, CaseGroup


# Backwards compatibility alias
TestItem = TestDefinition

__all__ = [
    "Case",
    "CaseGroup",
    "CaseGroupIterateModifier",
    "Run",
    "TestDefinition",
    "RueRun",
    "RueTestDefinition",
    "CaseIterateModifier",
    "Modifier",
    "ParameterSet",
    "ParametrizeModifier",
    "RepeatModifier",
    "RunEnvironment",
    "RunResult",
    "TestExecution",
    "TestItem",  # alias
    "TestResult",
    "TestStatus",
]
