"""Runtime state for resource resolution."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from rue.context.scopes import ScopeContext, ScopeOwner
from rue.resources.models import ResourceSpec, ResolverScopeState, ScheduledTeardown
from rue.resources.snapshot import SyncGraph


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

    def claim_resolution(self, spec: ResourceSpec, owner: ScopeOwner) -> bool:
        """Claim responsibility for resolving one uncached resource."""
        scope_state = self.state_for_owner(owner)
        if spec in scope_state.cache or spec in scope_state.pending:
            return False
        scope_state.pending[spec] = asyncio.get_running_loop().create_future()
        return True

    async def wait_resolution(self, spec: ResourceSpec, owner: ScopeOwner) -> Any:
        """Wait for another caller's resource resolution."""
        pending = self.state_for_owner(owner).pending[spec]
        return await asyncio.shield(pending)

    def commit_resolution(
        self,
        spec: ResourceSpec,
        owner: ScopeOwner,
        value: Any,
    ) -> None:
        """Store a resolved resource and release pending waiters."""
        scope_state = self.state_for_owner(owner)
        pending = scope_state.pending.pop(spec)
        scope_state.cache[spec] = value
        pending.set_result(value)

    def fail_resolution(
        self,
        spec: ResourceSpec,
        owner: ScopeOwner,
        error: BaseException,
    ) -> None:
        """Release pending waiters after resource resolution fails."""
        pending = self.state_for_owner(owner).pending.pop(spec)
        pending.set_exception(error)
        pending.exception()

    def record_teardown(self, teardown: ScheduledTeardown) -> None:
        """Record a generator teardown for live state."""
        if not self.is_shadow:
            self.state_for_owner(teardown.owner).teardowns.append(teardown)

    def cached_resources_by_spec(self) -> dict[ResourceSpec, Any]:
        """Return cached values keyed by provider spec."""
        result: dict[ResourceSpec, Any] = {}
        for scope_state in self._scopes.values():
            result.update(scope_state.cache)
        return result

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
    ) -> list[ScheduledTeardown]:
        """Remove and return teardowns for one owner."""
        scope_state = self.state_for_owner(owner)
        teardowns = scope_state.teardowns
        scope_state.teardowns = []
        return teardowns

    def clear(self, owner: ScopeOwner) -> None:
        """Clear cache and pending resolutions for one owner."""
        scope_state = self.state_for_owner(owner)
        scope_state.cache.clear()
        scope_state.pending.clear()

    def scope_owners(self) -> tuple[ScopeOwner, ...]:
        """Return all known runtime owners."""
        return tuple(self._scopes)
