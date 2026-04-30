"""Runtime state for resource resolution."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass, field
from typing import Any

from rue.context.scopes import ScopeContext, ScopeOwner
from rue.models import Spec
from rue.resources.models import (
    LoadedResourceDef,
    ResourceSpec,
)
from rue.resources.snapshot import SyncGraph


@dataclass(slots=True)
class ResourceTeardownRecord:
    """Generator resource teardown record."""

    spec: ResourceSpec
    owner: ScopeOwner
    definition: LoadedResourceDef
    generator: Generator[Any, None, None] | AsyncGenerator[Any, None]
    consumer_spec: Spec
    direct_dependencies: tuple[ResourceSpec, ...]


@dataclass(slots=True)
class ResolverScopeState:
    """Mutable state owned by one resource scope key."""

    cache: dict[ResourceSpec, Any] = field(default_factory=dict)
    pending: dict[ResourceSpec, asyncio.Future[Any]] = field(
        default_factory=dict
    )
    teardowns: list[ResourceTeardownRecord] = field(default_factory=list)


@dataclass(slots=True)
class ResourceStore:
    """Mutable resource state shared by resolver execution views."""

    _shadow: bool
    sync_graph: SyncGraph
    sync_lock: threading.RLock = field(default_factory=threading.RLock)
    _scopes: dict[ScopeOwner, ResolverScopeState] = field(default_factory=dict)

    @classmethod
    def main(cls, *, sync_actor_id: int = 0) -> ResourceStore:
        """Create live resource state."""
        return cls(_shadow=False, sync_graph=SyncGraph(actor_id=sync_actor_id))

    @classmethod
    def shadow(cls, *, sync_actor_id: int = 0) -> ResourceStore:
        """Create shadow resource state for worker hydration."""
        return cls(_shadow=True, sync_graph=SyncGraph(actor_id=sync_actor_id))

    @property
    def is_shadow(self) -> bool:
        """Return whether this state skips live teardown execution."""
        return self._shadow

    def state_for_owner(self, owner: ScopeOwner) -> ResolverScopeState:
        """Return mutable state for one owner."""
        return self._scopes.setdefault(owner, ResolverScopeState())

    async def get_or_create(
        self,
        spec: ResourceSpec,
        owner: ScopeOwner,
        create: Any,
    ) -> Any:
        """Return a cached value or create it behind a pending future."""
        scope_state = self.state_for_owner(owner)
        missing = object()
        value = scope_state.cache.get(spec, missing)
        if value is not missing:
            return value

        pending = scope_state.pending.get(spec)
        if pending is None:
            pending = asyncio.get_running_loop().create_future()
            scope_state.pending[spec] = pending
            try:
                value = await create()
            except Exception as error:
                pending.set_exception(error)
                pending.exception()
                raise
            else:
                scope_state.cache[spec] = value
                pending.set_result(value)
            finally:
                scope_state.pending.pop(spec, None)
            return value

        try:
            return await pending
        finally:
            if pending.cancelled():
                scope_state.pending.pop(spec, None)

    def record_teardown(self, teardown: ResourceTeardownRecord) -> None:
        """Record a generator teardown for live state."""
        if not self.is_shadow:
            self.state_for_owner(teardown.owner).teardowns.append(teardown)

    def cached_resource_instances(
        self,
    ) -> dict[tuple[ScopeOwner, ResourceSpec], Any]:
        """Return cached values keyed by provider and runtime owner."""
        return {
            (owner, spec): value
            for owner, scope_state in self._scopes.items()
            for spec, value in scope_state.cache.items()
        }

    def cached_resources_by_spec(self) -> dict[ResourceSpec, Any]:
        """Return cached values keyed by provider spec."""
        return {
            spec: value
            for (_owner, spec), value in (
                self.cached_resource_instances().items()
            )
        }

    def set(self, spec: ResourceSpec, owner: ScopeOwner, value: Any) -> None:
        """Set a cached runtime value."""
        self.state_for_owner(owner).cache[spec] = value

    def get(self, spec: ResourceSpec, owner: ScopeOwner) -> Any:
        """Return a cached runtime value."""
        return self.state_for_owner(owner).cache[spec]

    def has(self, spec: ResourceSpec, owner: ScopeOwner) -> bool:
        """Return whether a runtime value is cached."""
        return spec in self.state_for_owner(owner).cache

    def visible_instances(self) -> dict[ResourceSpec, Any]:
        """Return cached values visible in the current scope context."""
        return {
            spec: value
            for owner, scope_state in self._scopes.items()
            for spec, value in scope_state.cache.items()
            if owner == ScopeContext.current_owner(spec.scope)
        }

    def pop_teardown_records(
        self, owner: ScopeOwner
    ) -> list[ResourceTeardownRecord]:
        """Remove and return teardowns for one owner."""
        scope_state = self.state_for_owner(owner)
        teardowns = scope_state.teardowns
        scope_state.teardowns = []
        return teardowns

    def clear(self, owner: ScopeOwner) -> None:
        """Clear cache and pending creations for one owner."""
        scope_state = self.state_for_owner(owner)
        scope_state.cache.clear()
        scope_state.pending.clear()

    def scope_owners(self) -> tuple[ScopeOwner, ...]:
        """Return all known runtime owners."""
        return tuple(self._scopes)
