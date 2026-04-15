"""Test factory for creating executable tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from rue.config import Config
from rue.testing.execution.composite import CompositeTest
from rue.testing.execution.interfaces import ExecutableTest
from rue.testing.execution.single import SingleTest
from rue.testing.models import (
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    ParamsIterateModifier,
    LoadedTestDef,
)
from rue.testing.tracing import TestTracer


@dataclass
class DefaultTestFactory:
    """Creates test instances with shared collaborators."""

    config: Config
    run_id: UUID | None = None
    semaphore: asyncio.Semaphore | None = None
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    on_complete: Callable | None = None
    on_trace_collected: Callable | None = None

    def build(
        self,
        definition: LoadedTestDef,
        params: dict[str, Any] | None = None,
    ) -> ExecutableTest:
        """Recursively build the full test tree from definition."""
        params = params or {}
        modifiers = definition.spec.modifiers

        if not modifiers:
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

        mod, *rest = modifiers
        rest_tuple = tuple(rest)

        if isinstance(mod, IterateModifier):
            children = [
                self.build(
                    replace(
                        definition,
                        spec=replace(
                            definition.spec,
                            modifiers=rest_tuple,
                            suffix=f"iterate={i}",
                        ),
                    ),
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

        if isinstance(mod, CasesIterateModifier):
            children = [
                self.build(
                    replace(
                        definition,
                        spec=replace(
                            definition.spec,
                            modifiers=rest_tuple,
                            suffix=repr(c.metadata) if c.metadata else None,
                            case_id=c.id,
                        ),
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

        if isinstance(mod, GroupsIterateModifier):
            children = [
                self.build(
                    replace(
                        definition,
                        spec=replace(
                            definition.spec,
                            modifiers=(
                                CasesIterateModifier(
                                    cases=tuple(g.cases),
                                    min_passes=g.min_passes,
                                ),
                                *rest_tuple,
                            ),
                            suffix=g.name,
                        ),
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

        if isinstance(mod, ParamsIterateModifier):
            children = [
                self.build(
                    replace(
                        definition,
                        spec=replace(
                            definition.spec,
                            modifiers=rest_tuple,
                            suffix=ps.suffix,
                        ),
                    ),
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

        raise NotImplementedError(f"Unknown modifier: {mod}")
