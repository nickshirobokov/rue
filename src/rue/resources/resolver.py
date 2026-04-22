"""Resource system for dependency injection."""

import asyncio
import inspect
import threading
from collections import deque
from collections.abc import AsyncGenerator, Generator, Sequence
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_RESOURCE_CONSUMER_KIND,
    CURRENT_RESOURCE_PROVIDER,
    CURRENT_RESOURCE_RESOLVER,
    CURRENT_TEST,
    bind,
)
from rue.resources.models import (
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


_RESOLUTION_PATH: ContextVar[tuple[ResourceSpec, ...]] = ContextVar(
    "resource_resolution_path",
    default=(),
)
_MAIN_SYNC_ACTOR_ID = 0


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
        self._registry = registry
        self._cache: dict[ResourceSpec, Any] = {}
        self._teardowns: list[
            tuple[
                ResourceSpec,
                LoadedResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
            ]
        ] = []
        self._parent = parent
        self._pending: dict[ResourceSpec, asyncio.Future[Any]] = {}
        self._shared_dependency_graph: dict[
            ResourceSpec, list[ResourceSpec]
        ] = parent._shared_dependency_graph if parent is not None else {}
        self._shadow_mode = shadow_mode
        self._sync_graph = SyncGraph(actor_id=sync_actor_id)
        self._sync_lock = threading.RLock()

    @property
    def cached_identities(self) -> dict[ResourceSpec, Any]:
        """Return a shallow copy of the identity-to-value cache."""
        return dict(self._cache)

    def direct_dependencies_for(
        self, identity: ResourceSpec
    ) -> list[ResourceSpec]:
        return list(self._shared_dependency_graph.get(identity, []))

    async def resolve(
        self,
        name: str,
        *,
        apply_injection_hook: bool = True,
    ) -> Any:
        test_ctx = CURRENT_TEST.get()
        request_path = (
            None
            if test_ctx is None
            else test_ctx.item.spec.module_path.resolve()
        )
        definition = self._registry.select(name, request_path).definition
        identity = definition.spec
        scope = identity.scope

        path = _RESOLUTION_PATH.get()
        if identity in path:
            cycle = " -> ".join(
                (
                    f"{key.scope.value}:{key.name}"
                    if key.provider_dir is None
                    else f"{key.scope.value}:{key.name}@{key.provider_dir}"
                )
                for key in (*path, identity)
            )
            raise RuntimeError(
                f"Circular resource dependency detected: {cycle}"
            )

        token = _RESOLUTION_PATH.set((*path, identity))
        try:
            owner = self._owner_resolver_for_scope(scope)
            missing = object()
            parent = CURRENT_RESOURCE_PROVIDER.get()
            if parent is not None:
                direct = self._shared_dependency_graph.get(parent.spec)
                if direct is None:
                    direct = self._shared_dependency_graph[parent.spec] = []
                if identity not in direct:
                    direct.append(identity)

            value = owner._cache.get(identity, missing)
            if value is missing:
                pending = owner._pending.get(identity)
                if pending is None:
                    pending = asyncio.get_running_loop().create_future()
                    owner._pending[identity] = pending
                    try:
                        value = await owner._resolve_uncached(
                            name=name,
                            definition=definition,
                            cache_key=identity,
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

            with (
                bind(CURRENT_RESOURCE_PROVIDER, definition),
                bind(CURRENT_RESOURCE_RESOLVER, owner),
            ):
                return await self._apply_hook(
                    definition.on_injection, name, value
                )
        finally:
            _RESOLUTION_PATH.reset(token)

    async def partially_resolve(
        self,
        unresolved_params: tuple[str, ...],
        resolved_params: dict[str, Any],
        *,
        apply_injection_hook: bool = True,
    ) -> dict[str, Any]:
        kwargs = dict(resolved_params)
        test_ctx = CURRENT_TEST.get()
        with (
            bind(CURRENT_RESOURCE_CONSUMER, test_ctx.item.spec.name),
            bind(CURRENT_RESOURCE_CONSUMER_KIND, "test"),
        ):
            for param in unresolved_params:
                kwargs[param] = await self.resolve(
                    param,
                    apply_injection_hook=apply_injection_hook,
                )
        return kwargs

    def fork_for_test(self) -> "ResourceResolver":
        """Create a child resolver for isolated TEST-scope execution."""
        child = ResourceResolver(self._registry, parent=self)
        child._cache = {
            key: value
            for key, value in self._cache.items()
            if key.scope is not Scope.TEST
        }
        child._sync_graph = self._sync_graph.clone()
        return child

    async def teardown(self) -> None:
        if self._shadow_mode:
            self._cache.clear()
            self._teardowns.clear()
            return

        teardown_errors: list[Exception] = []

        for key, definition, generator in reversed(self._teardowns):
            with (
                bind(CURRENT_RESOURCE_PROVIDER, definition),
                bind(CURRENT_RESOURCE_RESOLVER, self),
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
                            f"Generator teardown failed for resource '{key.name}': {e}"
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
        self._teardowns.clear()

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
            return

        owner = self._owner_resolver_for_scope(scope)
        matching: list[
            tuple[
                ResourceSpec,
                LoadedResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
            ]
        ] = []
        to_keep: list[
            tuple[
                ResourceSpec,
                LoadedResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
            ]
        ] = []

        for teardown in owner._teardowns:
            if teardown[0].scope == scope:
                matching.append(teardown)
            else:
                to_keep.append(teardown)

        owner._teardowns = matching
        try:
            await owner.teardown()
        finally:
            owner._teardowns = to_keep
            for key in tuple(owner._cache):
                if key.scope == scope:
                    del owner._cache[key]

    def export_sync_snapshot(
        self,
        resources: Sequence[str] | Sequence[ResourceSpec],
        *,
        request_path: Path | None = None,
        sync_actor_id: int,
    ) -> ResolverSyncSnapshot:
        """Build a CRDT transfer snapshot for the given resource closure."""
        identities = self._snapshot_identities(resources)
        ordered_identities = self._topological_sort_snapshot_identities(
            identities
        )
        self.flush_live_changes(identities)

        root_keys = [identity.snapshot_key for identity in identities]
        payload = self._sync_graph.payload(root_keys)
        export_graph = SyncGraph(actor_id=_MAIN_SYNC_ACTOR_ID)
        export_graph.sync_payload(payload)
        return ResolverSyncSnapshot(
            res_specs=tuple(identities),
            request_path=(str(request_path) if request_path else None),
            graph_update=export_graph.doc.get_update(None),
            base_state=export_graph.doc.get_state(),
            resolution_order=tuple(ordered_identities),
            sync_actor_id=sync_actor_id,
        )

    @classmethod
    async def hydrate_from_sync_snapshot(
        cls,
        snapshot: ResolverSyncSnapshot,
        registry: ResourceRegistry,
    ) -> "ResourceResolver":
        resolver = cls(
            registry,
            shadow_mode=True,
            sync_actor_id=snapshot.sync_actor_id,
        )
        request_path = (
            Path(snapshot.request_path) if snapshot.request_path else None
        )

        for identity in snapshot.resolution_order:
            definition = registry.select(identity.name, request_path).definition
            await resolver._resolve_uncached(
                name=identity.name,
                definition=definition,
                cache_key=identity,
            )
        resolver._sync_graph = SyncGraph.from_update(
            snapshot.graph_update,
            actor_id=snapshot.sync_actor_id,
        )
        payload = resolver._sync_graph.payload(
            identity.snapshot_key for identity in snapshot.res_specs
        )
        resolver._sync_graph.set_baseline(payload)
        resolver._materialize_payload(payload)
        return resolver

    def flush_live_changes(
        self,
        resources: Sequence[str] | Sequence[ResourceSpec],
    ) -> None:
        """Push current live Python state into the canonical CRDT graph."""
        identities = self._snapshot_identities(resources)
        if not identities:
            return
        self._sync_graph.sync_live_roots(self._live_root_map(identities))

    def sync_update_since(
        self,
        base_state: bytes,
        resources: Sequence[str] | Sequence[ResourceSpec],
    ) -> bytes:
        """Return the CRDT update for the given resources since ``base_state``."""
        self.flush_live_changes(resources)
        return self._sync_graph.doc.get_update(base_state)

    def apply_sync_update(
        self,
        snapshot: ResolverSyncSnapshot,
        sync_update: bytes,
    ) -> None:
        """Merge a worker CRDT update and patch changed state onto live objects."""
        identities = list(snapshot.res_specs)
        if not identities:
            return

        merge_order = [
            *[identity for identity in identities if identity.scope is not Scope.TEST],
            *[identity for identity in identities if identity.scope is Scope.TEST],
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

    def _snapshot_identities(
        self,
        resources: Sequence[str] | Sequence[ResourceSpec],
    ) -> list[ResourceSpec]:
        resource_items = list(resources)
        if not resource_items:
            return []
        if all(isinstance(name, str) for name in resource_items):
            names = cast("list[str]", resource_items)
            closure = self._collect_snapshot_closure(
                names, self._cache, self._shared_dependency_graph
            )
            return [
                replace(
                    identity,
                    dependencies=tuple(d.name for d in dependencies),
                )
                for identity, dependencies in closure.items()
            ]
        if all(isinstance(spec, ResourceSpec) for spec in resource_items):
            specs = cast("list[ResourceSpec]", resource_items)
            return [
                replace(
                    identity,
                    dependencies=tuple(
                        dependency.name
                        for dependency in self._shared_dependency_graph.get(
                            identity,
                            (),
                        )
                    ),
                )
                for identity in specs
            ]
        msg = "resources must be list[str] or list[ResourceSpec]"
        raise TypeError(msg)

    async def _resolve_uncached(
        self,
        *,
        name: str,
        definition: LoadedResourceDef,
        cache_key: ResourceSpec,
    ) -> Any:
        with (
            bind(CURRENT_RESOURCE_PROVIDER, definition),
            bind(CURRENT_RESOURCE_RESOLVER, self),
        ):
            with (
                bind(CURRENT_RESOURCE_CONSUMER, name),
                bind(CURRENT_RESOURCE_CONSUMER_KIND, "resource"),
            ):
                kwargs = {
                    dependency: await self.resolve(dependency)
                    for dependency in cache_key.dependencies
                }

            match definition:
                case LoadedResourceDef(is_async_generator=True):
                    async_generator = cast(
                        "AsyncGenerator[Any, None]", definition.fn(**kwargs)
                    )
                    value = await anext(async_generator)
                    if not self._shadow_mode:
                        self._teardowns.append(
                            (cache_key, definition, async_generator)
                        )
                case LoadedResourceDef(is_generator=True):
                    generator = cast(
                        "Generator[Any, None, None]", definition.fn(**kwargs)
                    )
                    value = next(generator)
                    if not self._shadow_mode:
                        self._teardowns.append(
                            (cache_key, definition, generator)
                        )
                case LoadedResourceDef(is_async=True):
                    value = await definition.fn(**kwargs)
                case _:
                    value = definition.fn(**kwargs)

            value = await self._apply_hook(definition.on_resolve, name, value)

        self._cache[cache_key] = value
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
            raise RuntimeError(
                f"Hook {hook.__name__} failed for resource '{resource_name}': {e}"
            ) from e
        return value

    @staticmethod
    def _collect_snapshot_closure(
        resource_names: list[str],
        cache: dict[ResourceSpec, Any],
        dep_graph: dict[ResourceSpec, list[ResourceSpec]],
    ) -> dict[ResourceSpec, list[ResourceSpec]]:
        """Expand resource names into the dependency closure for a transfer snapshot."""
        name_to_identity = {identity.name: identity for identity in cache}
        for name in resource_names:
            if name not in name_to_identity:
                msg = f"Resource {name!r} is not present in the resolver cache"
                raise ValueError(msg)
        closure: dict[ResourceSpec, list[ResourceSpec]] = {}
        visited: set[ResourceSpec] = set()
        queue: deque[ResourceSpec] = deque(
            name_to_identity[name] for name in resource_names
        )

        while queue:
            identity = queue.popleft()
            if identity in visited:
                continue
            visited.add(identity)

            dependencies = list(dep_graph.get(identity, ()))
            closure[identity] = dependencies
            queue.extend(
                dependency
                for dependency in dependencies
                if dependency not in visited
            )

        return closure

    @staticmethod
    def _topological_sort_snapshot_identities(
        identities: list[ResourceSpec],
    ) -> list[ResourceSpec]:
        """Topologically sort identities for worker-side snapshot replay."""
        identity_map = {identity.name: identity for identity in identities}
        if not identity_map:
            return []

        in_degree = dict.fromkeys(identity_map, 0)
        dependents: dict[str, list[str]] = {name: [] for name in identity_map}

        for name, identity in identity_map.items():
            for dependency in identity.dependencies:
                if dependency in identity_map:
                    in_degree[name] += 1
                    dependents[dependency].append(name)

        queue: deque[str] = deque(
            name for name, degree in in_degree.items() if degree == 0
        )
        order: list[ResourceSpec] = []

        while queue:
            name = queue.popleft()
            order.append(identity_map[name])
            for dependent in dependents[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(identity_map):
            resolved = {identity.name for identity in order}
            unresolved = set(identity_map) - resolved
            msg = f"Circular dependency in snapshot resources: {unresolved}"
            raise RuntimeError(msg)

        return order
