"""Runtime state for resource resolution."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.models import Spec
from rue.patching.runtime import PatchHandle, PatchOwner
from rue.resources.models import LoadedResourceDef, ResourceSpec, Scope
from rue.resources.snapshot import SyncGraph


class ResolverLifecycleMode(StrEnum):
    """Runtime behavior for a resolver state."""

    LIVE = auto()
    SHADOW = auto()


@dataclass(frozen=True, slots=True)
class ResolverExecutionContext:
    """Consumer execution context used to choose resource owners."""

    execution_id: UUID
    module_path: Path

    @classmethod
    def from_consumer(
        cls,
        execution_id: UUID,
        consumer_spec: Spec,
    ) -> ResolverExecutionContext:
        """Build context from an execution id and consumer spec."""
        module_path = consumer_spec.module_path
        if module_path is None:
            module_path = Path("<unknown>")
        return cls(
            execution_id=execution_id,
            module_path=module_path.resolve(),
        )


@dataclass(frozen=True, slots=True)
class ResolverScopeOwner:
    """Runtime owner for a resource or patch lifecycle."""

    scope: Scope
    execution_id: UUID | None = None
    module_path: Path | None = None

    @classmethod
    def for_resource_scope(
        cls,
        scope: Scope,
        context: ResolverExecutionContext,
    ) -> ResolverScopeOwner:
        """Build the owner key for a resource scope in this context."""
        match scope:
            case Scope.TEST:
                return cls(scope=scope, execution_id=context.execution_id)
            case Scope.MODULE:
                return cls(scope=scope, module_path=context.module_path)
            case Scope.RUN:
                return cls(scope=scope)

    @classmethod
    def for_patch_owner(cls, owner: PatchOwner) -> ResolverScopeOwner:
        """Build the owner key for a patch owner."""
        match owner.scope:
            case Scope.TEST:
                return cls(scope=owner.scope, execution_id=owner.execution_id)
            case Scope.MODULE:
                return cls(scope=owner.scope, module_path=owner.module_path)
            case Scope.RUN:
                return cls(scope=owner.scope)


@dataclass(frozen=True, slots=True)
class ResourceCacheKey:
    """Cache key for one provider instance owned by one runtime scope."""

    spec: ResourceSpec
    owner: ResolverScopeOwner


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
    patch_handles: list[PatchHandle] = field(default_factory=list)


@dataclass(slots=True)
class ResolverState:
    """Mutable runtime state shared by resolver execution views."""

    lifecycle_mode: ResolverLifecycleMode
    sync_graph: SyncGraph
    sync_lock: threading.RLock = field(default_factory=threading.RLock)
    _scopes: dict[ResolverScopeOwner, ResolverScopeState] = field(
        default_factory=dict
    )

    @classmethod
    def main(cls, *, sync_actor_id: int = 0) -> ResolverState:
        """Create live resource state."""
        return cls(
            lifecycle_mode=ResolverLifecycleMode.LIVE,
            sync_graph=SyncGraph(actor_id=sync_actor_id),
        )

    @classmethod
    def shadow(cls, *, sync_actor_id: int = 0) -> ResolverState:
        """Create shadow resource state for worker hydration."""
        return cls(
            lifecycle_mode=ResolverLifecycleMode.SHADOW,
            sync_graph=SyncGraph(actor_id=sync_actor_id),
        )

    @property
    def is_shadow(self) -> bool:
        """Return whether this state skips live teardown execution."""
        return self.lifecycle_mode is ResolverLifecycleMode.SHADOW

    def cache_key_for(
        self,
        spec: ResourceSpec,
        context: ResolverExecutionContext,
    ) -> ResourceCacheKey:
        """Build the runtime instance key for a provider spec."""
        return ResourceCacheKey(
            spec=spec,
            owner=ResolverScopeOwner.for_resource_scope(spec.scope, context),
        )

    def state_for_owner(self, owner: ResolverScopeOwner) -> ResolverScopeState:
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

    def register_patch(self, handle: PatchHandle) -> None:
        """Attach a patch handle to its owning scope state."""
        owner = ResolverScopeOwner.for_patch_owner(handle.owner)
        self.state_for_owner(owner).patch_handles.append(handle)

    def pop_teardown_records(
        self, owner: ResolverScopeOwner
    ) -> list[ResourceTeardownRecord]:
        """Remove and return teardowns for one owner."""
        scope_state = self.state_for_owner(owner)
        teardowns = scope_state.teardowns
        scope_state.teardowns = []
        return teardowns

    def clear_scope_owner(self, owner: ResolverScopeOwner) -> None:
        """Clear cache and pending creations for one owner."""
        scope_state = self.state_for_owner(owner)
        scope_state.cache.clear()
        scope_state.pending.clear()

    def pop_patch_handles(self, owner: ResolverScopeOwner) -> list[PatchHandle]:
        """Remove and return patch handles for one owner."""
        scope_state = self.state_for_owner(owner)
        handles = scope_state.patch_handles
        scope_state.patch_handles = []
        return handles

    def scope_owners_for(self, scope: Scope) -> tuple[ResolverScopeOwner, ...]:
        """Return owners matching a lifecycle scope."""
        return tuple(owner for owner in self._scopes if owner.scope is scope)

    def scope_owners(self) -> tuple[ResolverScopeOwner, ...]:
        """Return all known runtime owners."""
        return tuple(self._scopes)
