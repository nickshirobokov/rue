"""Runtime state for resource resolution."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any

from rue.context.scopes import Scope, ScopeOwner
from rue.models import Spec
from rue.resources.models import (
    LoadedResourceDef,
    ResourceSpec,
)
from rue.resources.snapshot import SyncGraph


class ResolverLifecycleMode(StrEnum):
    """Runtime behavior for a resource store."""

    LIVE = auto()
    SHADOW = auto()


@dataclass(frozen=True, slots=True)
class ResourceCacheKey:
    """Cache key for one provider instance owned by one runtime scope."""

    spec: ResourceSpec
    owner: ScopeOwner


@dataclass(slots=True)
class ResourceTeardownRecord:
    """Generator resource teardown record."""

    key: ResourceCacheKey
    definition: LoadedResourceDef
    generator: Generator[Any, None, None] | AsyncGenerator[Any, None]
    consumer_spec: Spec
    direct_dependencies: tuple[ResourceSpec, ...]


@dataclass(slots=True)
class ResolverScopeState:
    """Mutable state owned by one resource scope key."""

    cache: dict[ResourceCacheKey, Any] = field(default_factory=dict)
    pending: dict[ResourceCacheKey, asyncio.Future[Any]] = field(
        default_factory=dict
    )
    teardowns: list[ResourceTeardownRecord] = field(default_factory=list)


@dataclass(slots=True)
class ResourceTransferState:
    """Mutable CRDT state used by resource transfer."""

    graph: SyncGraph
    lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass(slots=True)
class ResourceStore:
    """Mutable resource state shared by resolver execution views."""

    lifecycle_mode: ResolverLifecycleMode
    transfer: ResourceTransferState
    _scopes: dict[ScopeOwner, ResolverScopeState] = field(
        default_factory=dict
    )

    @classmethod
    def main(cls, *, sync_actor_id: int = 0) -> ResourceStore:
        """Create live resource state."""
        return cls(
            lifecycle_mode=ResolverLifecycleMode.LIVE,
            transfer=ResourceTransferState(SyncGraph(actor_id=sync_actor_id)),
        )

    @classmethod
    def shadow(cls, *, sync_actor_id: int = 0) -> ResourceStore:
        """Create shadow resource state for worker hydration."""
        return cls(
            lifecycle_mode=ResolverLifecycleMode.SHADOW,
            transfer=ResourceTransferState(SyncGraph(actor_id=sync_actor_id)),
        )

    @property
    def is_shadow(self) -> bool:
        """Return whether this state skips live teardown execution."""
        return self.lifecycle_mode is ResolverLifecycleMode.SHADOW

    def cache_key_for(
        self,
        spec: ResourceSpec,
        owner: ScopeOwner,
    ) -> ResourceCacheKey:
        """Build the runtime instance key for a provider spec."""
        return ResourceCacheKey(spec=spec, owner=owner)

    def state_for_owner(self, owner: ScopeOwner) -> ResolverScopeState:
        """Return mutable state for one owner."""
        return self._scopes.setdefault(owner, ResolverScopeState())

    async def get_or_create_instance(
        self,
        key: ResourceCacheKey,
        create: Any,
    ) -> Any:
        """Return a cached value or create it behind a pending future."""
        scope_state = self.state_for_owner(key.owner)
        missing = object()
        value = scope_state.cache.get(key, missing)
        if value is not missing:
            return value

        pending = scope_state.pending.get(key)
        if pending is None:
            pending = asyncio.get_running_loop().create_future()
            scope_state.pending[key] = pending
            try:
                value = await create()
            except Exception as error:
                pending.set_exception(error)
                pending.exception()
                raise
            else:
                scope_state.cache[key] = value
                pending.set_result(value)
            finally:
                scope_state.pending.pop(key, None)
            return value

        try:
            return await pending
        finally:
            if pending.cancelled():
                scope_state.pending.pop(key, None)

    def record_teardown(self, teardown: ResourceTeardownRecord) -> None:
        """Record a generator teardown for live state."""
        if not self.is_shadow:
            self.state_for_owner(teardown.key.owner).teardowns.append(teardown)

    def cached_resource_instances(self) -> dict[ResourceCacheKey, Any]:
        """Return cached values keyed by provider and runtime owner."""
        return {
            key: value
            for scope_state in self._scopes.values()
            for key, value in scope_state.cache.items()
        }

    def cached_instances_for_owner(
        self,
        owner: ScopeOwner,
    ) -> dict[ResourceCacheKey, Any]:
        """Return cached values visible to one runtime owner."""
        return {
            key: value
            for key, value in self.cached_resource_instances().items()
            if key.owner == owner
        }

    def cached_resources_by_spec(self) -> dict[ResourceSpec, Any]:
        """Return cached values keyed by provider spec."""
        return {
            key.spec: value
            for key, value in self.cached_resource_instances().items()
        }

    def cache_instance(self, key: ResourceCacheKey, value: Any) -> None:
        """Set a cached runtime value."""
        self.state_for_owner(key.owner).cache[key] = value

    def cached_instance(self, key: ResourceCacheKey) -> Any:
        """Return a cached runtime value."""
        return self.state_for_owner(key.owner).cache[key]

    def cached_instance_or_none(self, key: ResourceCacheKey) -> Any | None:
        """Return a cached runtime value when present."""
        return self.state_for_owner(key.owner).cache.get(key)

    def has_cached_instance(self, key: ResourceCacheKey) -> bool:
        """Return whether a runtime value is cached."""
        return key in self.state_for_owner(key.owner).cache

    def pop_teardown_records(
        self, owner: ScopeOwner
    ) -> list[ResourceTeardownRecord]:
        """Remove and return teardowns for one owner."""
        scope_state = self.state_for_owner(owner)
        teardowns = scope_state.teardowns
        scope_state.teardowns = []
        return teardowns

    def clear_scope_owner(self, owner: ScopeOwner) -> None:
        """Clear cache and pending creations for one owner."""
        scope_state = self.state_for_owner(owner)
        scope_state.cache.clear()
        scope_state.pending.clear()

    def scope_owners_for(self, scope: Scope) -> tuple[ScopeOwner, ...]:
        """Return owners matching a lifecycle scope."""
        return tuple(owner for owner in self._scopes if owner.scope is scope)

    def scope_owners(self) -> tuple[ScopeOwner, ...]:
        """Return all known runtime owners."""
        return tuple(self._scopes)
