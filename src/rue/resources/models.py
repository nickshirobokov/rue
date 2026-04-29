"""Resource model types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rue.models import Spec
from rue.context.scopes import Scope


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
class ResourceTransferSnapshot:
    """CRDT-backed transfer payload for reconstructing resources in a worker."""

    resource_specs: tuple[ResourceSpec, ...]
    graph_update: bytes
    base_state: bytes
    roots: tuple[ResourceSpec, ...] = field(default_factory=tuple)
    autouse: tuple[ResourceSpec, ...] = field(default_factory=tuple)
    injections: dict[str, ResourceSpec] = field(default_factory=dict)
    dependencies: dict[ResourceSpec, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    resolution_order: tuple[ResourceSpec, ...] = field(default_factory=tuple)
    actor_id: int = 0
