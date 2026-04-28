"""Resource system for dependency injection."""

import asyncio
import contextlib
import inspect
import threading
from collections.abc import AsyncGenerator, Generator, Iterator, Sequence
from typing import Any, cast
from uuid import UUID

from rue.context.runtime import ResourceTransactionContext
from rue.models import Spec
from rue.patching.runtime import PatchHandle
from rue.resources.models import (
    LoadedResourceDef,
    ResolverSyncSnapshot,
    ResourceGraph,
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


_MAIN_SYNC_ACTOR_ID = 0

type ResourceTeardown = tuple[
    ResourceSpec,
    LoadedResourceDef,
    Generator[Any, None, None] | AsyncGenerator[Any, None],
    Spec,
    tuple[ResourceSpec, ...],
]


class ResourceResolver:
    """Resolves and caches resources for test execution."""

    def __init__(
        self,
        registry: ResourceRegistry,
        *,
        parent: "ResourceResolver | None" = None,
        shadow_mode: bool = False,
        sync_actor_id: int = _MAIN_SYNC_ACTOR_ID,
    ) -> None:
        self.registry = registry
        self._cache: dict[ResourceSpec, Any] = {}
        self._teardowns: list[ResourceTeardown] = []
        self._parent = parent
        self._pending: dict[ResourceSpec, asyncio.Future[Any]] = {}
        self._shadow_mode = shadow_mode
        self._sync_graph = SyncGraph(actor_id=sync_actor_id)
        self._sync_lock = threading.RLock()
        self._patch_handles: list[PatchHandle] = []

    @property
    def cached_identities(self) -> dict[ResourceSpec, Any]:
        """Return a shallow copy of the identity-to-value cache."""
        return dict(self._cache)

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
        owner = handle.owner
        resolver = (
            self
            if owner.scope is Scope.TEST
            else self._owner_resolver_for_scope(owner.scope)
        )
        resolver._patch_handles.append(handle)

    async def resolve_consumer(
        self,
        key: UUID,
        params: dict[str, Any],
        *,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
    ) -> dict[str, Any]:
        """Resolve all resources needed by one compiled consumer key."""
        graph = self.registry.graph
        kwargs = dict(params)
        for identity in graph.autouse_by_key[key]:
            await self.resolve_resource(
                identity,
                consumer_spec=consumer_spec,
                apply_injection_hook=apply_injection_hook,
            )
        for name, identity in graph.injections_by_key[key].items():
            kwargs[name] = await self.resolve_resource(
                identity,
                consumer_spec=consumer_spec,
                apply_injection_hook=apply_injection_hook,
            )
        return kwargs

    async def resolve_resource(
        self,
        identity: ResourceSpec,
        *,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
    ) -> Any:
        """Resolve one concrete resource identity from a compiled graph."""
        graph = self.registry.graph
        definition = self.registry.definition(identity)
        scope = identity.scope
        direct_dependencies = graph.dependencies_by_spec[identity]

        owner = self._owner_resolver_for_scope(scope)
        missing = object()
        value = owner._cache.get(identity, missing)
        if value is missing:
            pending = owner._pending.get(identity)
            if pending is None:
                pending = asyncio.get_running_loop().create_future()
                owner._pending[identity] = pending
                try:
                    value = await owner._resolve_uncached(
                        graph=graph,
                        identity=identity,
                        consumer_spec=consumer_spec,
                    )
                except Exception as error:
                    pending.set_exception(error)
                    pending.exception()
                    raise
                else:
                    pending.set_result(value)
                finally:
                    owner._pending.pop(identity, None)
            else:
                try:
                    value = await pending
                finally:
                    if pending.cancelled():
                        owner._pending.pop(identity, None)

        if owner is not self:
            self._cache[identity] = value

        if not apply_injection_hook:
            return value

        with owner.open_transaction(
            consumer_spec=consumer_spec,
            provider_spec=identity,
            direct_dependencies=direct_dependencies,
        ):
            return await self._apply_hook(
                definition.on_injection,
                identity.name,
                value,
            )

    def fork_for_test(self) -> "ResourceResolver":
        """Create a child resolver for isolated TEST-scope execution."""
        child = ResourceResolver(
            self.registry,
            parent=self,
        )
        child._cache = {
            key: value
            for key, value in self._cache.items()
            if key.scope is not Scope.TEST
        }
        child._sync_graph = self._sync_graph.clone()
        return child

    async def teardown(self) -> None:
        """Tear down resources and patches owned by this resolver."""
        if self._shadow_mode:
            self._cache.clear()
            self._teardowns.clear()
            self._undo_all_patches()
            return

        teardown_errors = await self._run_teardowns(self._teardowns)
        self._teardowns.clear()
        self._undo_all_patches()
        self._raise_teardown_errors(teardown_errors)

    async def _run_teardowns(
        self,
        teardowns: Sequence[ResourceTeardown],
    ) -> list[Exception]:
        teardown_errors: list[Exception] = []

        for (
            key,
            definition,
            generator,
            consumer_spec,
            direct_dependencies,
        ) in reversed(teardowns):
            with self.open_transaction(
                consumer_spec=consumer_spec,
                provider_spec=key,
                direct_dependencies=direct_dependencies,
            ):
                try:
                    if definition.is_async_generator:
                        await anext(
                            cast("AsyncGenerator[Any, None]", generator), None
                        )
                    else:
                        next(
                            cast("Generator[Any, None, None]", generator), None
                        )
                except Exception as e:
                    teardown_errors.append(
                        RuntimeError(
                            "Generator teardown failed for resource "
                            f"'{key.name}': {e}"
                        )
                    )

                if key in self._cache:
                    try:
                        await self._apply_hook(
                            definition.on_teardown,
                            key.name,
                            self._cache[key],
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
        if self._shadow_mode:
            for key in tuple(self._cache):
                if key.scope is scope:
                    del self._cache[key]
            self._undo_patches_for_scope(scope)
            return

        owner = self._owner_resolver_for_scope(scope)
        matching: list[ResourceTeardown] = []
        to_keep: list[ResourceTeardown] = []

        for teardown in owner._teardowns:
            if teardown[0].scope == scope:
                matching.append(teardown)
            else:
                to_keep.append(teardown)

        owner._teardowns = to_keep
        try:
            teardown_errors = await owner._run_teardowns(matching)
        finally:
            for key in tuple(owner._cache):
                if key.scope == scope:
                    del owner._cache[key]
            owner._undo_patches_for_scope(scope)
        owner._raise_teardown_errors(teardown_errors)

    def _undo_all_patches(self) -> None:
        for handle in reversed(self._patch_handles):
            handle.undo()
        self._patch_handles.clear()

    def _undo_patches_for_scope(self, scope: Scope) -> None:
        keep: list[PatchHandle] = []
        for handle in self._patch_handles:
            if handle.owner.scope is scope:
                handle.undo()
            else:
                keep.append(handle)
        self._patch_handles = keep

    def export_sync_snapshot(
        self,
        key: UUID,
        *,
        sync_actor_id: int,
    ) -> ResolverSyncSnapshot:
        """Build a CRDT transfer snapshot for the given resource closure."""
        graph = self.registry.graph
        resource_order = graph.order_by_key[key]
        identities = self._sync_identities(resource_order)
        self.flush_live_changes(identities)

        root_keys = [identity.snapshot_key for identity in identities]
        payload = self._sync_graph.payload(root_keys)
        export_graph = SyncGraph(actor_id=_MAIN_SYNC_ACTOR_ID)
        export_graph.sync_payload(payload)
        return ResolverSyncSnapshot(
            res_specs=tuple(identities),
            resource_graph=graph.slice(key),
            graph_update=export_graph.doc.get_update(None),
            base_state=export_graph.doc.get_state(),
            resource_order=resource_order,
            sync_actor_id=sync_actor_id,
        )

    @classmethod
    async def hydrate_from_sync_snapshot(
        cls,
        snapshot: ResolverSyncSnapshot,
        registry: ResourceRegistry,
        *,
        consumer_spec: Spec,
    ) -> "ResourceResolver":
        """Build a shadow resolver from a serialized sync snapshot."""
        resolver = cls(
            registry,
            shadow_mode=True,
            sync_actor_id=snapshot.sync_actor_id,
        )
        await resolver.hydrate_sync_snapshot(
            snapshot,
            consumer_spec=consumer_spec,
        )
        return resolver

    async def hydrate_sync_snapshot(
        self,
        snapshot: ResolverSyncSnapshot,
        *,
        consumer_spec: Spec,
    ) -> None:
        """Hydrate this resolver from a serialized sync snapshot."""
        self.registry.graph = snapshot.resource_graph
        self._sync_graph = SyncGraph(actor_id=snapshot.sync_actor_id)

        for identity in snapshot.resource_order:
            if not identity.sync:
                continue
            if identity in self._cache:
                continue
            await self._resolve_uncached(
                graph=snapshot.resource_graph,
                identity=identity,
                consumer_spec=consumer_spec,
            )
        self._sync_graph = SyncGraph.from_update(
            snapshot.graph_update,
            actor_id=snapshot.sync_actor_id,
        )
        payload = self._sync_graph.payload(
            identity.snapshot_key for identity in snapshot.res_specs
        )
        self._sync_graph.set_baseline(payload)
        self._materialize_payload(payload)

    def flush_live_changes(
        self,
        resources: Sequence[ResourceSpec],
    ) -> None:
        """Push current live Python state into the canonical CRDT graph."""
        identities = self._sync_identities(resources)
        if not identities:
            return
        self._sync_graph.sync_live_roots(self._live_root_map(identities))

    def sync_update_since(
        self,
        base_state: bytes,
        resources: Sequence[ResourceSpec],
    ) -> bytes:
        """Return the CRDT update since ``base_state``."""
        self.flush_live_changes(resources)
        return self._sync_graph.doc.get_update(base_state)

    def apply_sync_update(
        self,
        snapshot: ResolverSyncSnapshot,
        sync_update: bytes,
    ) -> None:
        """Merge worker CRDT updates onto live objects."""
        identities = list(snapshot.res_specs)
        if not identities:
            return

        merge_order = [
            *[
                identity
                for identity in identities
                if identity.scope is not Scope.TEST
            ],
            *[
                identity
                for identity in identities
                if identity.scope is Scope.TEST
            ],
        ]
        root_keys = [identity.snapshot_key for identity in merge_order]

        with self._sync_lock:
            transport = SyncGraph.from_update(
                snapshot.graph_update,
                actor_id=_MAIN_SYNC_ACTOR_ID,
            )
            transport.object_ids = dict(self._sync_graph.object_ids)
            transport.path_ids = dict(self._sync_graph.path_ids)
            transport.next_local_id = self._sync_graph.next_local_id
            baseline_payload = transport.payload(root_keys)
            transport.sync_live_roots(self._live_root_map(merge_order))
            transport.apply_update(sync_update)
            after_payload = transport.payload(root_keys)
            self._apply_payload_delta(baseline_payload, after_payload)
            self._sync_graph.sync_payload(after_payload)
            self._refresh_sync_counter()

    def _owner_resolver_for_scope(self, scope: Scope) -> "ResourceResolver":
        if scope is not Scope.TEST and self._parent is not None:
            return self._parent._owner_resolver_for_scope(scope)
        return self

    def _materialize_payload(self, payload: dict[str, Any]) -> None:
        roots = {
            identity.snapshot_key: self._cache.get(identity)
            for identity in self._cache
            if identity.snapshot_key in payload["root_ids"]
        }
        applier = SnapshotApplier(
            payload,
            object_ids=self._sync_graph.object_ids,
        )
        patched_roots = applier.apply_roots(roots)
        self._sync_graph.object_ids = applier.object_ids
        self._sync_graph.path_ids = build_path_ids(payload)
        self._sync_graph.set_baseline(payload)
        self._refresh_sync_counter()
        key_to_identity = {
            identity.snapshot_key: identity for identity in self._cache
        }
        for root_key, value in patched_roots.items():
            identity = key_to_identity.get(root_key)
            if identity is not None:
                self._cache[identity] = value

    def _apply_payload_delta(
        self,
        before_payload: dict[str, Any],
        after_payload: dict[str, Any],
    ) -> None:
        roots = {
            identity.snapshot_key: self._cache.get(identity)
            for identity in self._cache
            if identity.snapshot_key in after_payload["root_ids"]
        }
        applier = SnapshotDeltaApplier(
            before_payload,
            after_payload,
            object_ids=self._sync_graph.object_ids,
        )
        patched_roots = applier.apply_roots(roots)
        self._sync_graph.object_ids = applier.object_ids
        self._sync_graph.path_ids = build_path_ids(after_payload)
        key_to_identity = {
            identity.snapshot_key: identity for identity in self._cache
        }
        for root_key, value in patched_roots.items():
            identity = key_to_identity.get(root_key)
            if identity is not None:
                self._cache[identity] = value

    def _live_root_map(
        self,
        identities: Sequence[ResourceSpec],
    ) -> dict[str, Any]:
        return {
            identity.snapshot_key: self._cache[identity]
            for identity in identities
            if identity in self._cache
        }

    @staticmethod
    def _sync_identities(
        resources: Sequence[ResourceSpec],
    ) -> list[ResourceSpec]:
        return [identity for identity in resources if identity.sync]

    def _refresh_sync_counter(self) -> None:
        prefix = f"{self._sync_graph.actor_id}:"
        counters = [
            int(node_id.removeprefix(prefix))
            for node_id in (
                *self._sync_graph.object_ids.values(),
                *self._sync_graph.path_ids.values(),
            )
            if node_id.startswith(prefix)
        ]
        self._sync_graph.next_local_id = max(
            counters,
            default=self._sync_graph.next_local_id - 1,
        ) + 1

    async def _resolve_uncached(
        self,
        *,
        graph: ResourceGraph,
        identity: ResourceSpec,
        consumer_spec: Spec,
    ) -> Any:
        definition = self.registry.definition(identity)
        direct_dependencies = graph.dependencies_by_spec[identity]
        with self.open_transaction(
            consumer_spec=consumer_spec,
            provider_spec=identity,
            direct_dependencies=direct_dependencies,
        ):
            kwargs = {
                dependency.name: (
                    await self.resolve_resource(
                        dependency,
                        consumer_spec=identity,
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
                    if not self._shadow_mode:
                        self._teardowns.append(
                            (
                                identity,
                                definition,
                                async_generator,
                                consumer_spec,
                                direct_dependencies,
                            )
                        )
                case LoadedResourceDef(is_generator=True):
                    generator = cast(
                        "Generator[Any, None, None]", definition.fn(**kwargs)
                    )
                    value = next(generator)
                    if not self._shadow_mode:
                        self._teardowns.append(
                            (
                                identity,
                                definition,
                                generator,
                                consumer_spec,
                                direct_dependencies,
                            )
                        )
                case LoadedResourceDef(is_async=True):
                    value = await definition.fn(**kwargs)
                case _:
                    value = definition.fn(**kwargs)

            value = await self._apply_hook(
                definition.on_resolve,
                identity.name,
                value,
            )

        self._cache[identity] = value
        return value

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
