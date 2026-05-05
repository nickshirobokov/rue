"""Resource transfer between live and shadow resolver states."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from rue.context.runtime import CURRENT_TEST
from rue.context.scopes import Scope, ScopeContext
from rue.models import Spec
from rue.resources.models import (
    ResourceSpec,
    StateSnapshot,
)
from rue.resources.snapshot import (
    SnapshotApplier,
    SnapshotDeltaApplier,
    SyncGraph,
    build_path_ids,
)


if TYPE_CHECKING:
    from rue.resources.resolver import DependencyResolver


_MAIN_SYNC_ACTOR_ID = 0


class StateTransfer:
    """Transfers resource state across resolver execution boundaries."""

    def __init__(self, resolver: DependencyResolver) -> None:
        self.resolver = resolver

    def export_snapshot(
        self,
        execution_id: UUID,
        *,
        actor_id: int,
    ) -> StateSnapshot:
        """Build a CRDT transfer snapshot for the given resource closure."""
        graph = self.resolver.registry.get_graph(execution_id)
        resources = self._syncable_resources(graph.resolution_order)
        sync_graph = self.resolver.resources.sync_graph
        sync_graph.sync_live_roots(
            self._live_snapshot_roots(resources)
        )
        payload = sync_graph.payload(
            self._snapshot_key(spec) for spec in resources
        )
        export_graph = SyncGraph(actor_id=_MAIN_SYNC_ACTOR_ID)
        export_graph.sync_payload(payload)
        return StateSnapshot(
            graph=graph,
            graph_update=export_graph.doc.get_update(None),
            base_state=export_graph.doc.get_state(),
            actor_id=actor_id,
        )

    async def hydrate(
        self,
        snapshot: StateSnapshot,
        *,
        consumer_spec: Spec,
    ) -> None:
        """Hydrate this resolver from a serialized transfer snapshot."""
        execution_id = CURRENT_TEST.get().execution_id
        graph = snapshot.graph
        self.resolver.registry.save_graph(execution_id, graph)
        sync_specs = self._syncable_resources(graph.resolution_order)

        transfer_graph = SyncGraph.from_update(
            snapshot.graph_update,
            actor_id=snapshot.actor_id,
        )
        payload = transfer_graph.payload(
            self._snapshot_key(spec) for spec in sync_specs
        )
        self.resolver.resources.sync_graph = SyncGraph(
            actor_id=snapshot.actor_id
        )

        for spec in sync_specs:
            root_key = self._snapshot_key(spec)
            dependencies = [*graph.dependencies[spec]]
            seen_dependencies: set[ResourceSpec] = set()
            needs_factory = root_key in payload["ignored_paths"]
            while dependencies and not needs_factory:
                dependency = dependencies.pop()
                if dependency in seen_dependencies:
                    continue
                seen_dependencies.add(dependency)
                needs_factory = not self.resolver.registry.get_definition(
                    dependency
                ).sync
                dependencies.extend(graph.dependencies[dependency])
            pending = (
                []
                if needs_factory
                else [payload["root_ids"][root_key]]
            )
            seen: set[str] = set()
            while pending:
                node_id = pending.pop()
                if node_id in seen:
                    continue
                seen.add(node_id)
                node = payload["nodes"][node_id]
                if node["kind"] == "opaque":
                    needs_factory = True
                    break
                pending.extend(SyncGraph._child_ids(node))

            if needs_factory:
                await self.resolver.resolve_resource(
                    spec=spec,
                    graph=graph,
                    consumer_spec=consumer_spec,
                    apply_injection_hook=False,
                )
        self.resolver.resources.sync_graph = transfer_graph
        self._materialize_payload(payload, sync_specs)

    def flush_visible_shared_resources(self) -> None:
        """Push visible non-test resources into the canonical CRDT graph."""
        store = self.resolver.resources
        store.sync_graph.sync_live_roots(
            self._live_snapshot_roots(
                spec
                for spec in store.visible_instances()
                if spec.scope is not Scope.TEST
            )
        )

    def update_since(self, snapshot: StateSnapshot) -> bytes:
        """Return the CRDT update since ``base_state``."""
        resources = self._syncable_resources(snapshot.graph.resolution_order)
        sync_graph = self.resolver.resources.sync_graph
        sync_graph.sync_live_roots(
            self._live_snapshot_roots(resources)
        )
        return sync_graph.doc.get_update(snapshot.base_state)

    def apply_update(
        self,
        snapshot: StateSnapshot,
        update: bytes,
    ) -> None:
        """Merge worker CRDT updates onto live objects."""
        store = self.resolver.resources
        resources = self._syncable_resources(
            snapshot.graph.resolution_order
        )
        if not resources:
            return

        merge_order = (
            *[spec for spec in resources if spec.scope is not Scope.TEST],
            *[spec for spec in resources if spec.scope is Scope.TEST],
        )
        root_keys = tuple(self._snapshot_key(spec) for spec in merge_order)

        with store.sync_lock:
            live_graph = store.sync_graph
            transport = SyncGraph.from_update(
                snapshot.graph_update,
                actor_id=_MAIN_SYNC_ACTOR_ID,
            )
            transport.object_ids = dict(live_graph.object_ids)
            transport.path_ids = dict(live_graph.path_ids)
            transport.next_local_id = live_graph.next_local_id
            baseline_payload = transport.payload(root_keys)
            transport.sync_live_roots(self._live_snapshot_roots(merge_order))
            transport.apply_update(update)
            after_payload = transport.payload(root_keys)
            self._materialize_payload(
                after_payload,
                merge_order,
                before_payload=baseline_payload,
            )
            live_graph.sync_payload(after_payload)
            self._refresh_sync_counter()

    def _materialize_payload(
        self,
        payload: dict[str, Any],
        resources: Iterable[ResourceSpec],
        *,
        before_payload: dict[str, Any] | None = None,
    ) -> None:
        graph = self.resolver.resources.sync_graph
        visible = self.resolver.resources.visible_instances()
        resources_by_key = {
            self._snapshot_key(spec): spec
            for spec in resources
        }
        roots = {
            key: visible[spec]
            for key, spec in resources_by_key.items()
            if spec in visible
        }
        applier = (
            SnapshotApplier(
                payload,
                object_ids=graph.object_ids,
            )
            if before_payload is None
            else SnapshotDeltaApplier(
                before_payload,
                payload,
                object_ids=graph.object_ids,
            )
        )
        for root_key, value in applier.apply_roots(roots).items():
            spec = resources_by_key[root_key]
            self.resolver.resources.set(
                spec,
                ScopeContext.current_owner(spec.scope),
                value,
            )

        graph.object_ids = applier.object_ids
        graph.path_ids = build_path_ids(payload)
        if before_payload is None:
            graph.set_baseline(payload)
            self._refresh_sync_counter()

    def _live_snapshot_roots(
        self,
        resources: Iterable[ResourceSpec],
    ) -> dict[str, Any]:
        visible = self.resolver.resources.visible_instances()
        return {
            self._snapshot_key(spec): visible[spec]
            for spec in resources
        }

    def _syncable_resources(
        self,
        resources: Iterable[ResourceSpec],
    ) -> tuple[ResourceSpec, ...]:
        return tuple(
            spec
            for spec in resources
            if self.resolver.registry.get_definition(spec).sync
        )

    @staticmethod
    def _snapshot_key(spec: ResourceSpec) -> str:
        return f"{spec.scope.value}|{spec.name}|{spec.module_path or ''}"

    def _refresh_sync_counter(self) -> None:
        graph = self.resolver.resources.sync_graph
        prefix = f"{graph.actor_id}:"
        counters = [
            int(node_id.removeprefix(prefix))
            for node_id in (
                *graph.object_ids.values(),
                *graph.path_ids.values(),
            )
            if node_id.startswith(prefix)
        ]
        graph.next_local_id = (
            max(
                counters,
                default=graph.next_local_id - 1,
            )
            + 1
        )
