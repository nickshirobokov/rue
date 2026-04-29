"""Resource model types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any
from uuid import UUID

from rue.models import Spec


class Scope(StrEnum):
    """Resource lifecycle scope."""

    TEST = auto()  # Fresh instance per test
    MODULE = auto()  # Shared across tests in same file
    RUN = auto()  # Shared across entire test run


@dataclass(slots=True, unsafe_hash=True)
class ResourceSpec(Spec):
    """Canonical spec for one resolved resource provider."""

    scope: Scope
    dependencies: tuple[str, ...] = field(default=(), compare=False)
    autouse: bool = field(default=False, compare=False)
    sync: bool = field(default=True, compare=False)

    @property
    def snapshot_key(self) -> str:
        """Return the stable identity used by resource transfer snapshots."""
        module_path = self.module_path
        return "|".join(
            (
                self.scope.value,
                self.name,
                "" if module_path is None else str(module_path),
                "" if module_path is None else str(module_path.parent),
            )
        )


@dataclass(slots=True, eq=False)
class LoadedResourceDef:
    """Definition of a registered resource."""

    spec: ResourceSpec
    fn: Callable[..., Any]
    is_async: bool
    is_generator: bool
    is_async_generator: bool
    on_resolve: Callable[[Any], Any] | None = None
    on_injection: Callable[[Any], Any] | None = None
    on_teardown: Callable[[Any], Any] | None = None


@dataclass(frozen=True, slots=True)
class DIGraph:
    """Precompiled concrete resource graph for known injection consumers."""

    roots_by_execution_id: dict[UUID, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    autouse_by_execution_id: dict[UUID, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    injections_by_execution_id: dict[UUID, dict[str, ResourceSpec]] = field(
        default_factory=dict
    )
    dependencies_by_resource: dict[ResourceSpec, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    resolution_order_by_execution_id: dict[UUID, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )

    def get_subgraph(self, execution_id: UUID) -> DIGraph:
        """Return the subgraph needed to execute one consumer key."""
        order = self.resolution_order_by_execution_id[execution_id]
        specs = set(order)
        return DIGraph(
            roots_by_execution_id={
                execution_id: self.roots_by_execution_id.get(execution_id, ())
            },
            autouse_by_execution_id={
                execution_id: self.autouse_by_execution_id.get(execution_id, ())
            },
            injections_by_execution_id={
                execution_id: dict(
                    self.injections_by_execution_id.get(execution_id, {})
                )
            },
            dependencies_by_resource={
                spec: dependencies
                for spec, dependencies in self.dependencies_by_resource.items()
                if spec in specs
            },
            resolution_order_by_execution_id={execution_id: order},
        )


@dataclass(frozen=True, slots=True)
class ResourceTransferSnapshot:
    """CRDT-backed transfer payload for reconstructing resources in a worker."""

    resource_specs: tuple[ResourceSpec, ...]
    execution_graph: DIGraph
    graph_update: bytes
    base_state: bytes
    resolution_order: tuple[ResourceSpec, ...] = field(default_factory=tuple)
    actor_id: int = 0
