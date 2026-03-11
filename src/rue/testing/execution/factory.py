"""Test factory for creating executable tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rue.testing.execution import iterated, parametrized, repeated, single
from rue.testing.execution.interfaces import Test, TestFactory
from rue.testing.execution.result_builder import ResultBuilder
from rue.testing.execution.tracer import TestTracer
from rue.testing.models import (
    CaseGroupIterateModifier,
    CaseIterateModifier,
    TestDefinition,
    ParametrizeModifier,
    RepeatModifier,
)


@dataclass
class DefaultTestFactory(TestFactory):
    """Creates test instances with shared collaborators."""

    tracer: TestTracer
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
                return single.SingleTest(
                    definition=definition,
                    params=params,
                    tracer=self.tracer,
                    result_builder=self.result_builder,
                )
            case [RepeatModifier() as mod, *_]:
                return repeated.RepeatedTest(
                    definition=definition,
                    params=params,
                    count=mod.count,
                    min_passes=mod.min_passes,
                    factory=self,
                )
            case [CaseIterateModifier() as mod, *_]:
                return iterated.CaseIteratedTest(
                    definition=definition,
                    params=params,
                    cases=mod.cases,
                    min_passes=mod.min_passes,
                    factory=self,
                )
            case [CaseGroupIterateModifier() as mod, *_]:
                return iterated.CaseGroupIteratedTest(
                    definition=definition,
                    params=params,
                    groups=mod.groups,
                    factory=self,
                )
            case [ParametrizeModifier() as mod, *_]:
                return parametrized.ParametrizedTest(
                    definition=definition,
                    params=params,
                    parameter_sets=mod.parameter_sets,
                    factory=self,
                )
            case _:
                raise NotImplementedError(f"Unknown modifier(s): {definition.modifiers}")
