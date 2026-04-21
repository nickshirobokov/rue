"""Test factory for creating executable tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from rue.config import Config
from rue.testing.execution.interfaces import ExecutableTest
from rue.testing.execution.local.composite import LocalCompositeTest
from rue.testing.execution.local.single import LocalSingleTest
from rue.testing.execution.remote.single import RemoteSingleTest
from rue.testing.execution.types import ExecutionBackend
from rue.testing.models import (
    BackendModifier,
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    ParamsIterateModifier,
    LoadedTestDef,
)
from rue.testing.tracing import build_test_tracer


@dataclass
class DefaultTestFactory:
    """Creates test instances with shared collaborators."""

    config: Config
    run_id: UUID
    semaphore: asyncio.Semaphore | None = None
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    on_complete: Callable | None = None
    _next_sync_actor_id: int = field(default=1, init=False, repr=False)

    def build(
        self,
        definition: LoadedTestDef,
        params: dict[str, Any] | None = None,
        backend: ExecutionBackend = ExecutionBackend.LOCAL,
    ) -> ExecutableTest:
        """Recursively build the full test tree from definition."""
        params = params or {}
        modifiers = definition.spec.modifiers

        if not modifiers:
            match backend:
                case ExecutionBackend.SUBPROCESS:
                    sync_actor_id = self._next_sync_actor_id
                    self._next_sync_actor_id += 1
                    return RemoteSingleTest(
                        definition=definition,
                        params=params,
                        config=self.config,
                        run_id=self.run_id,
                        sync_actor_id=sync_actor_id,
                        is_stopped=self.is_stopped,
                        on_complete=self.on_complete,
                    )
                case ExecutionBackend.LOCAL:
                    return LocalSingleTest(
                        definition=definition,
                        params=params,
                        tracer=build_test_tracer(
                            config=self.config,
                            run_id=self.run_id,
                        ),
                        semaphore=self.semaphore,
                        is_stopped=self.is_stopped,
                        on_complete=self.on_complete,
                    )
                case _:
                    raise NotImplementedError(f"Unknown backend: {backend}")

        mod, *rest = modifiers
        rest_tuple = tuple(rest)

        match mod:
            case BackendModifier(backend=sub_backend):
                return self.build(
                    replace(
                        definition,
                        spec=replace(definition.spec, modifiers=rest_tuple),
                    ),
                    params,
                    backend=sub_backend,
                )
            case IterateModifier(count=count, min_passes=min_passes):
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
                        backend=backend,
                    )
                    for i in range(count)
                ]
                return LocalCompositeTest(
                    definition=definition,
                    min_passes=min_passes,
                    children=children,
                    on_complete=self.on_complete,
                )
            case CasesIterateModifier(cases=cases, min_passes=min_passes):
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
                        backend=backend,
                    )
                    for c in cases
                ]
                return LocalCompositeTest(
                    definition=definition,
                    min_passes=min_passes,
                    children=children,
                    on_complete=self.on_complete,
                )
            case GroupsIterateModifier(groups=groups, min_passes=min_passes):
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
                        backend=backend,
                    )
                    for g in groups
                ]
                return LocalCompositeTest(
                    definition=definition,
                    min_passes=min_passes,
                    children=children,
                    on_complete=self.on_complete,
                )
            case ParamsIterateModifier(
                parameter_sets=parameter_sets, min_passes=min_passes
            ):
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
                        backend=backend,
                    )
                    for ps in parameter_sets
                ]
                return LocalCompositeTest(
                    definition=definition,
                    min_passes=min_passes,
                    children=children,
                    on_complete=self.on_complete,
                )
            case _:
                raise NotImplementedError(f"Unknown modifier: {mod}")
