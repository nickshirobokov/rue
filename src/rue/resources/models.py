"""Resource model types."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rue.context.scopes import Scope
from rue.models import Spec


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
    resolve_hook: Callable[[Any], Any] | None = None
    injection_hook: Callable[[Any], Any] | None = None
    teardown_hook: Callable[[Any], Any] | None = None

    async def on_resolve(self, value: Any) -> Any:
        hook = self.resolve_hook
        if hook is None:
            return value
        result = hook(value)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def on_injection(self, value: Any) -> Any:
        hook = self.injection_hook
        if hook is None:
            return value
        result = hook(value)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def on_teardown(self, value: Any) -> Any:
        hook = self.teardown_hook
        if hook is None:
            return value
        result = hook(value)
        if inspect.isawaitable(result):
            result = await result
        return result


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
