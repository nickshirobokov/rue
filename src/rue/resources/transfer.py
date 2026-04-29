"""Resource transfer between live and shadow resolver states."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from rue.context.runtime import CURRENT_TEST
from rue.context.scopes import ScopeContext
from rue.models import Spec
from rue.resources.models import ResourceSpec, ResourceTransferSnapshot, Scope
from rue.resources.snapshot import (
    SnapshotApplier,
    SnapshotDeltaApplier,
    SyncGraph,
    build_path_ids,
)


if TYPE_CHECKING:
    from rue.resources.resolver import ResourceResolver
    from rue.resources.state import ResourceCacheKey, ResourceTransferState


_MAIN_SYNC_ACTOR_ID = 0


class ResourceTransfer:
    """Transfers resource state across resolver execution boundaries."""

    def __init__(self, resolver: ResourceResolver) -> None:
        self.resolver = resolver

    def export_snapshot(
        self,
        execution_id: UUID,
        *,
        actor_id: int,
    ) -> ResourceTransferSnapshot:
        """Build a CRDT transfer snapshot for the given resource closure."""
        registry = self.resolver.registry.slice_registry(execution_id)
        resolution_order = registry.resolution_order_by_execution_id[
            execution_id
        ]
        resources = self._syncable_resources(resolution_order)
        self.flush_live_resources(resources)

        root_keys = [spec.snapshot_key for spec in resources]
        payload = self.state.graph.payload(root_keys)
        export_graph = SyncGraph(actor_id=_MAIN_SYNC_ACTOR_ID)
        export_graph.sync_payload(payload)
        return ResourceTransferSnapshot(
            resource_specs=tuple(resources),
            graph_update=export_graph.doc.get_update(None),
            base_state=export_graph.doc.get_state(),
            roots=registry.roots_by_execution_id[execution_id],
            autouse=registry.autouse_by_execution_id[execution_id],
            injections=registry.injections_by_execution_id[execution_id],
            dependencies=registry.dependencies_by_resource,
            resolution_order=resolution_order,
            actor_id=actor_id,
        )

    async def hydrate(
        self,
        snapshot: ResourceTransferSnapshot,
        *,
        consumer_spec: Spec,
    ) -> None:
        """Hydrate this resolver from a serialized transfer snapshot."""
        execution_id = CURRENT_TEST.get().execution_id
        self.resolver.registry.roots_by_execution_id = {
            execution_id: snapshot.roots
        }
        self.resolver.registry.autouse_by_execution_id = {
            execution_id: snapshot.autouse
        }
        self.resolver.registry.injections_by_execution_id = {
            execution_id: dict(snapshot.injections)
        }
        self.resolver.registry.dependencies_by_resource = dict(
            snapshot.dependencies
        )
        self.resolver.registry.resolution_order_by_execution_id = {
            execution_id: snapshot.resolution_order
        }
        self.resolver.resources.transfer.graph = SyncGraph(
            actor_id=snapshot.actor_id
        )

        for spec in snapshot.resolution_order:
            if not spec.sync:
                continue
            key = self.resolver.resources.cache_key_for(
                spec,
                ScopeContext.current_owner(spec.scope),
            )
            if self.resolver.resources.has_cached_instance(key):
                continue
            value = await self.resolver._resolve_uncached(
                key=key,
                consumer_spec=consumer_spec,
            )
            self.resolver.resources.cache_instance(key, value)
        self.resolver.resources.transfer.graph = SyncGraph.from_update(
            snapshot.graph_update,
            actor_id=snapshot.actor_id,
        )
        payload = self.state.graph.payload(
            spec.snapshot_key for spec in snapshot.resource_specs
        )
        self.state.graph.set_baseline(payload)
        self._materialize_payload(payload)

    def flush_live_resources(
        self,
        resources: Sequence[ResourceSpec],
    ) -> None:
        """Push current live Python state into the canonical CRDT graph."""
        synced = self._syncable_resources(resources)
        if not synced:
            return
        self.state.graph.sync_live_roots(self._live_snapshot_roots(synced))

    def flush_visible_shared_resources(self) -> None:
        """Push visible non-test resources into the canonical CRDT graph."""
        self.flush_live_resources(
            [
                key.spec
                for key in self._cached_instances_visible_to_view()
                if key.spec.scope is not Scope.TEST
            ]
        )

    def update_since(
        self,
        base_state: bytes,
        resources: Sequence[ResourceSpec],
    ) -> bytes:
        """Return the CRDT update since ``base_state``."""
        self.flush_live_resources(resources)
        return self.state.graph.doc.get_update(base_state)

    def apply_update(
        self,
        snapshot: ResourceTransferSnapshot,
        update: bytes,
    ) -> None:
        """Merge worker CRDT updates onto live objects."""
        resource_specs = list(snapshot.resource_specs)
        if not resource_specs:
            return

        merge_order = [
            *[spec for spec in resource_specs if spec.scope is not Scope.TEST],
            *[spec for spec in resource_specs if spec.scope is Scope.TEST],
        ]
        root_keys = [spec.snapshot_key for spec in merge_order]

        with self.resolver.resources.transfer.lock:
            transport = SyncGraph.from_update(
                snapshot.graph_update,
                actor_id=_MAIN_SYNC_ACTOR_ID,
            )
            transport.object_ids = dict(self.state.graph.object_ids)
            transport.path_ids = dict(self.state.graph.path_ids)
            transport.next_local_id = self.state.graph.next_local_id
            baseline_payload = transport.payload(root_keys)
            transport.sync_live_roots(self._live_snapshot_roots(merge_order))
            transport.apply_update(update)
            after_payload = transport.payload(root_keys)
            self._apply_payload_delta(baseline_payload, after_payload)
            self.state.graph.sync_payload(after_payload)
            self._refresh_sync_counter()

    @property
    def state(self) -> ResourceTransferState:
        """Return the resolver transfer state."""
        return self.resolver.resources.transfer

    def _materialize_payload(self, payload: dict[str, Any]) -> None:
        roots = {
            key.spec.snapshot_key: value
            for key, value in self._cached_instances_visible_to_view().items()
            if key.spec.snapshot_key in payload["root_ids"]
        }
        applier = SnapshotApplier(
            payload,
            object_ids=self.state.graph.object_ids,
        )
        patched_roots = applier.apply_roots(roots)
        self.state.graph.object_ids = applier.object_ids
        self.state.graph.path_ids = build_path_ids(payload)
        self.state.graph.set_baseline(payload)
        self._refresh_sync_counter()
        key_to_spec = {
            key.spec.snapshot_key: key
            for key in self._cached_instances_visible_to_view()
        }
        for root_key, value in patched_roots.items():
            key = key_to_spec.get(root_key)
            if key is not None:
                self.resolver.resources.cache_instance(key, value)

    def _apply_payload_delta(
        self,
        before_payload: dict[str, Any],
        after_payload: dict[str, Any],
    ) -> None:
        roots = {
            key.spec.snapshot_key: value
            for key, value in self._cached_instances_visible_to_view().items()
            if key.spec.snapshot_key in after_payload["root_ids"]
        }
        applier = SnapshotDeltaApplier(
            before_payload,
            after_payload,
            object_ids=self.state.graph.object_ids,
        )
        patched_roots = applier.apply_roots(roots)
        self.state.graph.object_ids = applier.object_ids
        self.state.graph.path_ids = build_path_ids(after_payload)
        key_to_spec = {
            key.spec.snapshot_key: key
            for key in self._cached_instances_visible_to_view()
        }
        for root_key, value in patched_roots.items():
            key = key_to_spec.get(root_key)
            if key is not None:
                self.resolver.resources.cache_instance(key, value)

    def _live_snapshot_roots(
        self,
        resources: Sequence[ResourceSpec],
    ) -> dict[str, Any]:
        return {
            key.spec.snapshot_key: value
            for key, value in self._cached_instances_visible_to_view().items()
            if key.spec in resources
        }

    def _cached_instances_visible_to_view(
        self,
    ) -> dict[ResourceCacheKey, Any]:
        return {
            key: value
            for key, value in (
                self.resolver.resources.cached_resource_instances().items()
            )
            if key.owner == ScopeContext.current_owner(key.spec.scope)
        }

    @staticmethod
    def _syncable_resources(
        resources: Sequence[ResourceSpec],
    ) -> list[ResourceSpec]:
        return [spec for spec in resources if spec.sync]

    def _refresh_sync_counter(self) -> None:
        prefix = f"{self.state.graph.actor_id}:"
        counters = [
            int(node_id.removeprefix(prefix))
            for node_id in (
                *self.state.graph.object_ids.values(),
                *self.state.graph.path_ids.values(),
            )
            if node_id.startswith(prefix)
        ]
        self.state.graph.next_local_id = (
            max(
                counters,
                default=self.state.graph.next_local_id - 1,
            )
            + 1
        )
