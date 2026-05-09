"""Case and static suite spec models."""

from rue.testing.models.case import Case, CaseFactory, CaseGroup
from rue.testing.models.edge import EdgeCaseFactory
from rue.testing.models.spec import (
    Locator,
    SetupFileRef,
    SuiteSpec,
    TestSpec,
)


__all__ = [
    "Case",
    "CaseFactory",
    "CaseGroup",
    "EdgeCaseFactory",
    "Locator",
    "SetupFileRef",
    "SuiteSpec",
    "TestSpec",
]
