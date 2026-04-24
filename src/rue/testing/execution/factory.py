"""Test factory for creating executable tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from rue.config import Config
from rue.testing.execution.composite import CompositeTest
from rue.testing.execution.base import ExecutableTest, ExecutionBackend
from rue.testing.execution.single import SingleTest
from rue.testing.models import (
    BackendModifier,
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    ParamsIterateModifier,
    LoadedTestDef,
)
from rue.testing.execution.queue import SessionQueue


@dataclass
class DefaultTestFactory:
    """Creates test instances with shared collaborators."""

    config: Config
    run_id: UUID
    semaphore: asyncio.Semaphore | None = None
    is_stopped: Callable[[], bool] = field(default=lambda: False)
    on_complete: Callable | None = None
    queue: SessionQueue | None = None
    _next_sync_actor_id: int = field(default=1, init=False, repr=False)

    def build(
        self,
        definition: LoadedTestDef,
        params: dict[str, Any] | None = None,
        backend: ExecutionBackend | None = None,
        *,
        enqueue: bool = True,
        node_key: str | None = None,
    ) -> ExecutableTest:
        """Recursively build the full test tree from definition."""
        params = params or {}
        backend = backend or ExecutionBackend.ASYNCIO
        node_key = node_key or definition.spec.full_name
        modifiers = definition.spec.modifiers

        if not modifiers:
            if backend is ExecutionBackend.SUBPROCESS:
                sync_actor_id = self._next_sync_actor_id
                self._next_sync_actor_id += 1
            else:
                sync_actor_id = 1
            match backend:
                case (
                    ExecutionBackend.SUBPROCESS
                    | ExecutionBackend.MAIN
                    | ExecutionBackend.MODULE_MAIN
                    | ExecutionBackend.ASYNCIO
                ):
                    test = SingleTest(
                        definition=definition,
                        params=params,
                        node_key=node_key,
                        backend=backend,
                        config=self.config,
                        run_id=self.run_id,
                        sync_actor_id=sync_actor_id,
                        semaphore=self.semaphore,
                        is_stopped=self.is_stopped,
                        on_complete=self.on_complete,
                    )
                case _:
                    raise NotImplementedError(f"Unknown backend: {backend}")
            if enqueue and self.queue is not None:
                self.queue.add(test)
            return test

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
                    enqueue=enqueue,
                    node_key=node_key,
                )
            case IterateModifier(count=count, min_passes=min_passes):
                children = [
                    self.build(
                        replace(
                            definition,
                            spec=replace(
                                definition.spec,
                                modifiers=rest_tuple,
                                suffix=f"i={i}",
                            ),
                        ),
                        params,
                        backend=backend,
                        enqueue=False,
                        node_key=self._child_node_key(
                            parent_node_key=node_key,
                            modifier_name=mod.display_name,
                            index=i,
                        ),
                    )
                    for i in range(count)
                ]
                test = CompositeTest(
                    definition=definition,
                    backend=backend,
                    min_passes=min_passes,
                    node_key=node_key,
                    children=children,
                    on_complete=self.on_complete,
                )
                if enqueue and self.queue is not None:
                    self.queue.add(test)
                return test
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
                        enqueue=False,
                        node_key=self._child_node_key(
                            parent_node_key=node_key,
                            modifier_name=mod.display_name,
                            index=index,
                            label=repr(c.metadata) if c.metadata else None,
                        ),
                    )
                    for index, c in enumerate(cases)
                ]
                test = CompositeTest(
                    definition=definition,
                    backend=backend,
                    min_passes=min_passes,
                    node_key=node_key,
                    children=children,
                    on_complete=self.on_complete,
                )
                if enqueue and self.queue is not None:
                    self.queue.add(test)
                return test
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
                        enqueue=False,
                        node_key=self._child_node_key(
                            parent_node_key=node_key,
                            modifier_name=mod.display_name,
                            index=index,
                            label=g.name,
                        ),
                    )
                    for index, g in enumerate(groups)
                ]
                test = CompositeTest(
                    definition=definition,
                    backend=backend,
                    min_passes=min_passes,
                    node_key=node_key,
                    children=children,
                    on_complete=self.on_complete,
                )
                if enqueue and self.queue is not None:
                    self.queue.add(test)
                return test
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
                        enqueue=False,
                        node_key=self._child_node_key(
                            parent_node_key=node_key,
                            modifier_name=mod.display_name,
                            index=index,
                            label=ps.suffix,
                        ),
                    )
                    for index, ps in enumerate(parameter_sets)
                ]
                test = CompositeTest(
                    definition=definition,
                    backend=backend,
                    min_passes=min_passes,
                    node_key=node_key,
                    children=children,
                    on_complete=self.on_complete,
                )
                if enqueue and self.queue is not None:
                    self.queue.add(test)
                return test
            case _:
                raise NotImplementedError(f"Unknown modifier: {mod}")

    @staticmethod
    def _child_node_key(
        *,
        parent_node_key: str,
        modifier_name: str,
        index: int,
        label: str | None = None,
    ) -> str:
        segment = f"{modifier_name}[{index}]"
        if label:
            segment = f"{segment}={label}"
        return f"{parent_node_key}/{segment}"
