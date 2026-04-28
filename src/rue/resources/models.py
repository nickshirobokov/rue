"""Resource model types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any

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
class ResourceGraph:
    """Precompiled concrete resource graph for known injection consumers."""

    roots_by_key: dict[str, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    autouse_by_key: dict[str, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    injections_by_key: dict[str, dict[str, ResourceSpec]] = field(
        default_factory=dict
    )
    dependencies_by_spec: dict[ResourceSpec, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    order_by_key: dict[str, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )

    def slice(self, key: str) -> ResourceGraph:
        """Return the subgraph needed to execute one consumer key."""
        order = self.order_by_key[key]
        specs = set(order)
        return ResourceGraph(
            roots_by_key={key: self.roots_by_key.get(key, ())},
            autouse_by_key={key: self.autouse_by_key.get(key, ())},
            injections_by_key={
                key: dict(self.injections_by_key.get(key, {}))
            },
            dependencies_by_spec={
                identity: dependencies
                for identity, dependencies in self.dependencies_by_spec.items()
                if identity in specs
            },
            order_by_key={key: order},
        )


@dataclass(frozen=True, slots=True)
class ResolverSyncSnapshot:
    """CRDT-backed transfer payload for reconstructing resources in a worker."""

    res_specs: tuple[ResourceSpec, ...]
    resource_graph: ResourceGraph
    graph_update: bytes
    base_state: bytes
    resource_order: tuple[ResourceSpec, ...] = field(default_factory=tuple)
    sync_actor_id: int = 0
