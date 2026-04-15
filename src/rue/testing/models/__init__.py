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
from rue.testing.models.spec import (
    SetupFileRef,
    TestLocator,
    TestSpec,
    TestSpecCollection,
)


__all__ = [
    "Case",
    "CaseGroup",
    "GroupsIterateModifier",
    "Run",
    "RunEnvironment",
    "RunResult",
    "SetupFileRef",
    "TestDefinition",
    "TestLocator",
    "TestSpec",
    "TestSpecCollection",
    "CasesIterateModifier",
    "IterateModifier",
    "Modifier",
    "ParameterSet",
    "ParamsIterateModifier",
    "TestExecution",
    "TestResult",
    "TestStatus",
]
