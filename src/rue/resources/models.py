"""Resource model types."""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Callable, Generator
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any

from rue.context.models import ScopeOwner
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
class StateSnapshot:
    """CRDT-backed transfer payload for reconstructing resources in a worker."""

    graph: ResourceGraph
    graph_update: bytes
    base_state: bytes
    actor_id: int = 0


@dataclass(slots=True)
class ScheduledTeardown:
    """Generator resource teardown record."""

    spec: ResourceSpec
    owner: ScopeOwner
    definition: LoadedResourceDef
    generator: Generator[Any, None, None] | AsyncGenerator[Any, None]
    consumer_spec: Spec
    direct_dependencies: tuple[ResourceSpec, ...]
