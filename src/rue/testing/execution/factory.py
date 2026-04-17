"""Test factory for creating executable tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
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
    pool: ProcessPoolExecutor | None = None

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
                    if self.pool is None:
                        raise RuntimeError(
                            "subprocess backend requires a ProcessPoolExecutor"
                        )
                    return RemoteSingleTest(
                        definition=definition,
                        params=params,
                        pool=self.pool,
                        is_stopped=self.is_stopped,
                        on_complete=self.on_complete,
                    )
                case ExecutionBackend.LOCAL:
                    return LocalSingleTest(
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
