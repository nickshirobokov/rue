"""Test factory for creating executable tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from rue.testing.execution.interfaces import Test, TestFactory
from rue.testing.execution.result_builder import ResultBuilder
from rue.testing.execution.composite import CompositeTest
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
        """Recursively build the full test tree from definition."""
        params = params or {}

        match definition.modifiers:
            case []:
                return SingleTest(
                    definition=definition,
                    params=params,
                    result_builder=self.result_builder,
                )

            case [IterateModifier() as mod, *rest]:
                children = [
                    self.build(
                        replace(definition, modifiers=rest, suffix=f"iterate={i}"),
                        params,
                    )
                    for i in range(mod.count)
                ]
                return CompositeTest(
                    definition=definition,
                    min_passes=mod.min_passes,
                    children=children,
                )

            case [CasesIterateModifier() as mod, *rest]:
                children = [
                    self.build(
                        replace(
                            definition,
                            modifiers=rest,
                            suffix=repr(c.metadata) if c.metadata else None,
                            case_id=c.id,
                        ),
                        {**params, "case": c},
                    )
                    for c in mod.cases
                ]
                return CompositeTest(
                    definition=definition,
                    min_passes=mod.min_passes,
                    children=children,
                )

            case [GroupsIterateModifier() as mod, *rest]:
                children = [
                    self.build(
                        replace(
                            definition,
                            modifiers=[
                                CasesIterateModifier(
                                    cases=tuple(g.cases),
                                    min_passes=g.min_passes,
                                ),
                                *rest,
                            ],
                            suffix=g.name,
                        ),
                        {**params, "group": g},
                    )
                    for g in mod.groups
                ]
                return CompositeTest(
                    definition=definition,
                    min_passes=mod.min_passes,
                    children=children,
                )

            case [ParamsIterateModifier() as mod, *rest]:
                children = [
                    self.build(
                        replace(definition, modifiers=rest, suffix=ps.suffix),
                        {**params, **ps.values},
                    )
                    for ps in mod.parameter_sets
                ]
                return CompositeTest(
                    definition=definition,
                    min_passes=mod.min_passes,
                    children=children,
                )

            case _:
                raise NotImplementedError(
                    f"Unknown modifier(s): {definition.modifiers}"
                )
