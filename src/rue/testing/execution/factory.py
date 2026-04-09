"""Test factory for creating executable tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from rue.config import RueConfig
from rue.testing.execution.composite import CompositeTest
from rue.testing.execution.interfaces import Test
from rue.testing.execution.single import SingleTest
from rue.testing.models import (
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    ParamsIterateModifier,
    TestDefinition,
)
from rue.testing.tracing import TestTracer


@dataclass
class DefaultTestFactory:
    """Creates test instances with shared collaborators."""

    config: RueConfig
    run_id: UUID | None = None
    semaphore: asyncio.Semaphore | None = None
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    on_complete: Callable | None = None
    on_trace_collected: Callable | None = None

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
                    tracer=TestTracer(
                        otel_enabled=self.config.otel,
                        run_id=self.run_id,
                    ),
                    semaphore=self.semaphore,
                    is_stopped=self.is_stopped,
                    on_complete=self.on_complete,
                    on_trace_collected=self.on_trace_collected,
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
                    on_complete=self.on_complete,
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
                    on_complete=self.on_complete,
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
                    on_complete=self.on_complete,
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
                    on_complete=self.on_complete,
                )

            case _:
                raise NotImplementedError(
                    f"Unknown modifier(s): {definition.modifiers}"
                )
