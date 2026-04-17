"""Testing models - pure data classes."""

from rue.testing.models.loaded import LoadedTestDef
from rue.testing.models.modifiers import (
    BackendModifier,
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    Modifier,
    ParameterSet,
    ParamsIterateModifier,
)
from rue.testing.models.executed import ExecutedTest
from rue.testing.models.result import TestResult, TestStatus
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
    "LoadedTestDef",
    "TestLocator",
    "TestSpec",
    "TestSpecCollection",
    "BackendModifier",
    "CasesIterateModifier",
    "IterateModifier",
    "Modifier",
    "ParameterSet",
    "ParamsIterateModifier",
    "ExecutedTest",
    "TestResult",
    "TestStatus",
]
