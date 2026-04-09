"""Test factory for creating executable tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rue.testing.execution.iterate import (
    CasesIterateTest,
    GroupsIterateTest,
    IterateTest,
    ParamsIterateTest,
)
from rue.testing.execution.interfaces import Test, TestFactory
from rue.testing.execution.result_builder import ResultBuilder
from rue.testing.execution.single import SingleTest
from rue.testing.models import (
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    ParamsIterateModifier,
    TestDefinition,
)


@dataclass
class DefaultTestFactory(TestFactory):
    """Creates test instances with shared collaborators."""

    result_builder: ResultBuilder

    def build(
        self,
        definition: TestDefinition,
        params: dict[str, Any] | None = None,
    ) -> Test:
        """Build appropriate executable test from definition."""
        params = params or {}

        match definition.modifiers:
            case []:
                return SingleTest(
                    definition=definition,
                    params=params,
                    result_builder=self.result_builder,
                )
            case [IterateModifier() as mod, *_]:
                return IterateTest(
                    definition=definition,
                    params=params,
                    count=mod.count,
                    min_passes=mod.min_passes,
                    factory=self,
                )
            case [CasesIterateModifier() as mod, *_]:
                return CasesIterateTest(
                    definition=definition,
                    params=params,
                    cases=mod.cases,
                    min_passes=mod.min_passes,
                    factory=self,
                )
            case [GroupsIterateModifier() as mod, *_]:
                return GroupsIterateTest(
                    definition=definition,
                    params=params,
                    groups=mod.groups,
                    min_passes=mod.min_passes,
                    factory=self,
                )
            case [ParamsIterateModifier() as mod, *_]:
                return ParamsIterateTest(
                    definition=definition,
                    params=params,
                    parameter_sets=mod.parameter_sets,
                    min_passes=mod.min_passes,
                    factory=self,
                )
            case _:
                raise NotImplementedError(
                    f"Unknown modifier(s): {definition.modifiers}"
                )
