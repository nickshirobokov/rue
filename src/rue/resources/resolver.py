"""Resource system for dependency injection."""

import contextlib
import inspect
from collections.abc import AsyncGenerator, Generator, Iterator, Sequence
from typing import Any, cast
from uuid import UUID

from rue.context.runtime import ResourceTransactionContext
from rue.models import Spec
from rue.patching.runtime import PatchHandle
from rue.resources.models import (
    DIGraph,
    LoadedResourceDef,
    ResolverSyncSnapshot,
    ResourceSpec,
    Scope,
)
from rue.resources.registry import ResourceRegistry
from rue.resources.snapshot import (
    SnapshotApplier,
    SnapshotDeltaApplier,
    SyncGraph,
    build_path_ids,
)
from rue.resources.state import (
    ResourceCacheKey,
    ResourceTeardownRecord,
    ResolverExecutionContext,
    ResolverScopeOwner,
    ResolverState,
)


_MAIN_SYNC_ACTOR_ID = 0
_DIRECT_EXECUTION_ID = UUID(int=0)


class ResourceResolver:
    """Resolves and caches resources for test execution."""

    def __init__(
        self,
        registry: ResourceRegistry,
        *,
        state: ResolverState | None = None,
        scope_context: ResolverExecutionContext | None = None,
        sync_actor_id: int = _MAIN_SYNC_ACTOR_ID,
    ) -> None:
        self.registry = registry
        self.state = state or ResolverState.main(sync_actor_id=sync_actor_id)
        self._scope_context = scope_context

    @property
    def cached_resources(self) -> dict[ResourceSpec, Any]:
        """Return a shallow copy of the identity-to-value cache."""
        return self.state.cached_resources_by_spec()

    def view_for_test(
        self,
        execution_id: UUID,
        consumer_spec: Spec,
    ) -> "ResourceResolver":
        """Return a scoped resolver view for one consumer execution."""
        return ResourceResolver(
            self.registry,
            state=self.state,
            scope_context=ResolverExecutionContext.from_consumer(
                execution_id,
                consumer_spec,
            ),
        )

    @contextlib.contextmanager
    def open_transaction(
        self,
        *,
        consumer_spec: Spec,
        provider_spec: Spec,
        direct_dependencies: tuple[ResourceSpec, ...] = (),
    ) -> Iterator[None]:
        """Bind consumer/provider attribution for resolver-owned work."""
        with ResourceTransactionContext(
            consumer_spec=consumer_spec,
            provider_spec=provider_spec,
            resolver=self,
            direct_dependencies=direct_dependencies,
        ):
            yield

    def register_patch(self, handle: PatchHandle) -> None:
        """Attach a patch handle to the resolver that owns its lifetime."""
        self.state.register_patch(handle)

    async def resolve_test_deps(
        self,
        execution_id: UUID,
        params: dict[str, Any],
        *,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
    ) -> dict[str, Any]:
        """Resolve all resources needed by one compiled test."""
        graph = self.registry.graph
        kwargs = dict(params)
        for spec in graph.autouse_by_execution_id[execution_id]:
            await self.resolve_resource(
                spec,
                consumer_spec=consumer_spec,
                apply_injection_hook=apply_injection_hook,
            )
        for name, spec in graph.injections_by_execution_id[execution_id].items():
            kwargs[name] = await self.resolve_resource(
                spec,
                consumer_spec=consumer_spec,
                apply_injection_hook=apply_injection_hook,
            )
        return kwargs

    async def resolve_resource(
        self,
        spec: ResourceSpec,
        *,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
        scope_context: ResolverExecutionContext | None = None,
    ) -> Any:
        """Resolve one concrete resource identity from a compiled graph."""
        graph = self.registry.graph
        definition = self.registry.get_definition(spec)
        direct_dependencies = graph.dependencies_by_resource[spec]
        scope_context = scope_context or self._scope_context_for(consumer_spec)
        key = self.state.cache_key_for(spec, scope_context)
        value = await self.state.get_or_create_instance(
            key,
            lambda: self._resolve_uncached(
                graph=graph,
                key=key,
                consumer_spec=consumer_spec,
                scope_context=scope_context,
            ),
        )

        if not apply_injection_hook:
            return value

        with self.open_transaction(
            consumer_spec=consumer_spec,
            provider_spec=spec,
            direct_dependencies=direct_dependencies,
        ):
            return await self._apply_hook(
                definition.on_injection,
                spec.name,
                value,
            )

    async def teardown(self) -> None:
        """Tear down resources and patches owned by this resolver."""
        teardown_errors: list[Exception] = []
        for owner in reversed(tuple(self.state.scope_owners())):
            if self.state.is_shadow:
                self.state.clear_scope_owner(owner)
                self._undo_patches(owner)
                continue
            teardown_errors.extend(
                await self._run_teardowns(self.state.pop_teardown_records(owner))
            )
            self.state.clear_scope_owner(owner)
            self._undo_patches(owner)
        self._raise_teardown_errors(teardown_errors)

    async def _run_teardowns(
        self,
        teardowns: Sequence[ResourceTeardownRecord],
    ) -> list[Exception]:
        teardown_errors: list[Exception] = []

        for teardown in reversed(teardowns):
            spec = teardown.key.spec
            with self.open_transaction(
                consumer_spec=teardown.consumer_spec,
                provider_spec=spec,
                direct_dependencies=teardown.direct_dependencies,
            ):
                try:
                    if teardown.definition.is_async_generator:
                        await anext(
                            cast(
                                "AsyncGenerator[Any, None]",
                                teardown.generator,
                            ),
                            None,
                        )
                    else:
                        next(
                            cast(
                                "Generator[Any, None, None]",
                                teardown.generator,
                            ),
                            None,
                        )
                except Exception as e:
                    teardown_errors.append(
                        RuntimeError(
                            "Generator teardown failed for resource "
                            f"'{spec.name}': {e}"
                        )
                    )

                if self.state.has_cached_instance(teardown.key):
                    value = self.state.cached_instance(teardown.key)
                    try:
                        await self._apply_hook(
                            teardown.definition.on_teardown,
                            spec.name,
                            value,
                        )
                    except RuntimeError as e:
                        teardown_errors.append(e)
        return teardown_errors

    @staticmethod
    def _raise_teardown_errors(teardown_errors: list[Exception]) -> None:
        match teardown_errors:
            case []:
                return
            case [error]:
                raise RuntimeError(error)
            case _:
                raise ExceptionGroup(
                    "Teardown errors occurred", teardown_errors
                )

    async def teardown_scope(self, scope: Scope) -> None:
        """Teardown only resources matching the given scope."""
        teardown_errors: list[Exception] = []
        for owner in self._scope_owners_to_teardown(scope):
            if self.state.is_shadow:
                self.state.clear_scope_owner(owner)
                self._undo_patches(owner)
                continue
            teardown_errors.extend(
                await self._run_teardowns(self.state.pop_teardown_records(owner))
            )
            self.state.clear_scope_owner(owner)
            self._undo_patches(owner)
        self._raise_teardown_errors(teardown_errors)

    def _scope_owners_to_teardown(
        self, scope: Scope
    ) -> tuple[ResolverScopeOwner, ...]:
        if self._scope_context is None:
            return self.state.scope_owners_for(scope)
        return (
            ResolverScopeOwner.for_resource_scope(scope, self._scope_context),
        )

    def _undo_patches(self, owner: ResolverScopeOwner) -> None:
        for handle in reversed(self.state.pop_patch_handles(owner)):
            handle.undo()

    def export_sync_snapshot(
        self,
        execution_id: UUID,
        *,
        sync_actor_id: int,
    ) -> ResolverSyncSnapshot:
        """Build a CRDT transfer snapshot for the given resource closure."""
        graph = self.registry.graph
        resolution_order = graph.resolution_order_by_execution_id[execution_id]
        resources = self._syncable_resources(resolution_order)
        self.flush_resources_to_sync_graph(resources)

        root_keys = [spec.snapshot_key for spec in resources]
        payload = self.state.sync_graph.payload(root_keys)
        export_graph = SyncGraph(actor_id=_MAIN_SYNC_ACTOR_ID)
        export_graph.sync_payload(payload)
        return ResolverSyncSnapshot(
            resource_specs=tuple(resources),
            execution_graph=graph.get_subgraph(execution_id),
            graph_update=export_graph.doc.get_update(None),
            base_state=export_graph.doc.get_state(),
            resolution_order=resolution_order,
            actor_id=sync_actor_id,
        )

    @classmethod
    async def from_sync_snapshot(
        cls,
        snapshot: ResolverSyncSnapshot,
        registry: ResourceRegistry,
        *,
        consumer_spec: Spec,
    ) -> "ResourceResolver":
        """Build a shadow resolver from a serialized sync snapshot."""
        resolver = cls(
            registry,
            state=ResolverState.shadow(sync_actor_id=snapshot.actor_id),
        )
        await resolver.load_sync_snapshot(
            snapshot,
            consumer_spec=consumer_spec,
        )
        return resolver

    async def load_sync_snapshot(
        self,
        snapshot: ResolverSyncSnapshot,
        *,
        consumer_spec: Spec,
    ) -> None:
        """Hydrate this resolver from a serialized sync snapshot."""
        self.registry.graph = snapshot.execution_graph
        self.state.sync_graph = SyncGraph(actor_id=snapshot.actor_id)

        for spec in snapshot.resolution_order:
            if not spec.sync:
                continue
            scope_context = self._scope_context_for(consumer_spec)
            key = self.state.cache_key_for(spec, scope_context)
            if self.state.has_cached_instance(key):
                continue
            value = await self._resolve_uncached(
                graph=snapshot.execution_graph,
                key=key,
                consumer_spec=consumer_spec,
                scope_context=scope_context,
            )
            self.state.cache_instance(key, value)
        self.state.sync_graph = SyncGraph.from_update(
            snapshot.graph_update,
            actor_id=snapshot.actor_id,
        )
        payload = self.state.sync_graph.payload(
            spec.snapshot_key for spec in snapshot.resource_specs
        )
        self.state.sync_graph.set_baseline(payload)
        self._materialize_payload(payload)

    def flush_resources_to_sync_graph(
        self,
        resources: Sequence[ResourceSpec],
    ) -> None:
        """Push current live Python state into the canonical CRDT graph."""
        synced = self._syncable_resources(resources)
        if not synced:
            return
        self.state.sync_graph.sync_live_roots(self._live_snapshot_roots(synced))

    def sync_update_for_resources_since(
        self,
        base_state: bytes,
        resources: Sequence[ResourceSpec],
    ) -> bytes:
        """Return the CRDT update since ``base_state``."""
        self.flush_resources_to_sync_graph(resources)
        return self.state.sync_graph.doc.get_update(base_state)

    def apply_sync_update(
        self,
        snapshot: ResolverSyncSnapshot,
        sync_update: bytes,
    ) -> None:
        """Merge worker CRDT updates onto live objects."""
        resource_specs = list(snapshot.resource_specs)
        if not resource_specs:
            return

        merge_order = [
            *[
                spec
                for spec in resource_specs
                if spec.scope is not Scope.TEST
            ],
            *[
                spec
                for spec in resource_specs
                if spec.scope is Scope.TEST
            ],
        ]
        root_keys = [spec.snapshot_key for spec in merge_order]

        with self.state.sync_lock:
            transport = SyncGraph.from_update(
                snapshot.graph_update,
                actor_id=_MAIN_SYNC_ACTOR_ID,
            )
            transport.object_ids = dict(self.state.sync_graph.object_ids)
            transport.path_ids = dict(self.state.sync_graph.path_ids)
            transport.next_local_id = self.state.sync_graph.next_local_id
            baseline_payload = transport.payload(root_keys)
            transport.sync_live_roots(self._live_snapshot_roots(merge_order))
            transport.apply_update(sync_update)
            after_payload = transport.payload(root_keys)
            self._apply_payload_delta(baseline_payload, after_payload)
            self.state.sync_graph.sync_payload(after_payload)
            self._refresh_sync_counter()

    def _materialize_payload(self, payload: dict[str, Any]) -> None:
        roots = {
            key.spec.snapshot_key: value
            for key, value in self._cached_instances_visible_to_view().items()
            if key.spec.snapshot_key in payload["root_ids"]
        }
        applier = SnapshotApplier(
            payload,
            object_ids=self.state.sync_graph.object_ids,
        )
        patched_roots = applier.apply_roots(roots)
        self.state.sync_graph.object_ids = applier.object_ids
        self.state.sync_graph.path_ids = build_path_ids(payload)
        self.state.sync_graph.set_baseline(payload)
        self._refresh_sync_counter()
        key_to_spec = {
            key.spec.snapshot_key: key
            for key in self._cached_instances_visible_to_view()
        }
        for root_key, value in patched_roots.items():
            key = key_to_spec.get(root_key)
            if key is not None:
                self.state.cache_instance(key, value)

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
            object_ids=self.state.sync_graph.object_ids,
        )
        patched_roots = applier.apply_roots(roots)
        self.state.sync_graph.object_ids = applier.object_ids
        self.state.sync_graph.path_ids = build_path_ids(after_payload)
        key_to_spec = {
            key.spec.snapshot_key: key
            for key in self._cached_instances_visible_to_view()
        }
        for root_key, value in patched_roots.items():
            key = key_to_spec.get(root_key)
            if key is not None:
                self.state.cache_instance(key, value)

    def _live_snapshot_roots(
        self,
        resources: Sequence[ResourceSpec],
    ) -> dict[str, Any]:
        return {
            key.spec.snapshot_key: value
            for key, value in self._cached_instances_visible_to_view().items()
            if key.spec in resources
        }

    def _cached_instances_visible_to_view(self) -> dict[ResourceCacheKey, Any]:
        if self._scope_context is None:
            return self.state.cached_resource_instances()
        return {
            key: value
            for key, value in self.state.cached_resource_instances().items()
            if key.owner
            == ResolverScopeOwner.for_resource_scope(
                key.spec.scope,
                self._scope_context,
            )
        }

    @staticmethod
    def _syncable_resources(
        resources: Sequence[ResourceSpec],
    ) -> list[ResourceSpec]:
        return [spec for spec in resources if spec.sync]

    def _refresh_sync_counter(self) -> None:
        prefix = f"{self.state.sync_graph.actor_id}:"
        counters = [
            int(node_id.removeprefix(prefix))
            for node_id in (
                *self.state.sync_graph.object_ids.values(),
                *self.state.sync_graph.path_ids.values(),
            )
            if node_id.startswith(prefix)
        ]
        self.state.sync_graph.next_local_id = max(
            counters,
            default=self.state.sync_graph.next_local_id - 1,
        ) + 1

    async def _resolve_uncached(
        self,
        *,
        graph: DIGraph,
        key: ResourceCacheKey,
        consumer_spec: Spec,
        scope_context: ResolverExecutionContext,
    ) -> Any:
        spec = key.spec
        definition = self.registry.get_definition(spec)
        direct_dependencies = graph.dependencies_by_resource[spec]
        with self.open_transaction(
            consumer_spec=consumer_spec,
            provider_spec=spec,
            direct_dependencies=direct_dependencies,
        ):
            kwargs = {
                dependency.name: (
                    await self.resolve_resource(
                        dependency,
                        consumer_spec=spec,
                        scope_context=scope_context,
                    )
                )
                for dependency in direct_dependencies
            }

            match definition:
                case LoadedResourceDef(is_async_generator=True):
                    async_generator = cast(
                        "AsyncGenerator[Any, None]", definition.fn(**kwargs)
                    )
                    value = await anext(async_generator)
                    self.state.record_teardown(
                        ResourceTeardownRecord(
                            key=key,
                            definition=definition,
                            generator=async_generator,
                            consumer_spec=consumer_spec,
                            direct_dependencies=direct_dependencies,
                        )
                    )
                case LoadedResourceDef(is_generator=True):
                    generator = cast(
                        "Generator[Any, None, None]", definition.fn(**kwargs)
                    )
                    value = next(generator)
                    self.state.record_teardown(
                        ResourceTeardownRecord(
                            key=key,
                            definition=definition,
                            generator=generator,
                            consumer_spec=consumer_spec,
                            direct_dependencies=direct_dependencies,
                        )
                    )
                case LoadedResourceDef(is_async=True):
                    value = await definition.fn(**kwargs)
                case _:
                    value = definition.fn(**kwargs)

            value = await self._apply_hook(
                definition.on_resolve,
                spec.name,
                value,
            )

        return value

    def _scope_context_for(self, consumer_spec: Spec) -> ResolverExecutionContext:
        if self._scope_context is not None:
            return self._scope_context
        return ResolverExecutionContext.from_consumer(
            _DIRECT_EXECUTION_ID, consumer_spec
        )

    async def _apply_hook(
        self, hook: Any, resource_name: str, value: Any
    ) -> Any:
        if hook is None:
            return value

        try:
            value = hook(value)
            if inspect.isawaitable(value):
                value = await value
        except Exception as e:
            msg = (
                f"Hook {hook.__name__} failed for resource "
                f"'{resource_name}': {e}"
            )
            raise RuntimeError(
                msg
            ) from e
        return value
