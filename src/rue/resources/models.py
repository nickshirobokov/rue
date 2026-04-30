"""Resource model types."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any

from rue.context.scopes import Scope
from rue.models import Spec


class ResourceFactoryKind(StrEnum):
    """Resource factory execution kind."""

    SYNC = auto()
    ASYNC = auto()
    GENERATOR = auto()
    ASYNC_GENERATOR = auto()


@dataclass(slots=True, unsafe_hash=True)
class ResourceSpec(Spec):
    """Canonical spec for one resolved resource provider."""

    scope: Scope

    @property
    def snapshot_key(self) -> str:
        """Return the stable identity used by resource transfer snapshots."""
        module_path = self.module_path
        return "|".join(
            (
                self.scope.value,
                self.name,
                "" if module_path is None else str(module_path),
            )
        )


@dataclass(slots=True, eq=False)
class LoadedResourceDef:
    """Definition of a registered resource."""

    spec: ResourceSpec
    fn: Callable[..., Any]
    factory_kind: ResourceFactoryKind
    dependencies: tuple[str, ...] = ()
    autouse: bool = False
    sync: bool = True
    resolve_hook: Callable[[Any], Any] | None = None
    injection_hook: Callable[[Any], Any] | None = None
    teardown_hook: Callable[[Any], Any] | None = None

    async def on_resolve(self, value: Any) -> Any:
        """Apply the resolve hook to a freshly created resource value."""
        hook = self.resolve_hook
        if hook is None:
            return value
        result = hook(value)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def on_injection(self, value: Any) -> Any:
        """Apply the injection hook before a resource reaches a consumer."""
        hook = self.injection_hook
        if hook is None:
            return value
        result = hook(value)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def on_teardown(self, value: Any) -> Any:
        """Apply the teardown hook before a resource leaves its owner."""
        hook = self.teardown_hook
        if hook is None:
            return value
        result = hook(value)
        if inspect.isawaitable(result):
            result = await result
        return result


@dataclass(frozen=True, slots=True)
class ResourceGraph:
    """Compiled resource graph for one execution consumer."""

    autouse: tuple[ResourceSpec, ...] = ()
    injections: dict[str, ResourceSpec] = field(default_factory=dict)
    dependencies: dict[ResourceSpec, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    resolution_order: tuple[ResourceSpec, ...] = ()

    @property
    def roots(self) -> tuple[ResourceSpec, ...]:
        """Return provider roots for this graph."""
        return (*self.autouse, *self.injections.values())


@dataclass(frozen=True, slots=True)
class ResourceTransferSnapshot:
    """CRDT-backed transfer payload for reconstructing resources in a worker."""

    resource_specs: tuple[ResourceSpec, ...]
    graph_update: bytes
    base_state: bytes
    autouse: tuple[ResourceSpec, ...] = field(default_factory=tuple)
    injections: dict[str, ResourceSpec] = field(default_factory=dict)
    dependencies: dict[ResourceSpec, tuple[ResourceSpec, ...]] = field(
        default_factory=dict
    )
    resolution_order: tuple[ResourceSpec, ...] = field(default_factory=tuple)
    actor_id: int = 0
