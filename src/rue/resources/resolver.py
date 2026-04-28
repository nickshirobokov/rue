"""Resource system for dependency injection."""

import asyncio
import contextlib
import inspect
import threading
from collections import deque
from collections.abc import AsyncGenerator, Generator, Iterator, Sequence
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from rue.context.runtime import (
    ResourceTransactionContext,
)
from rue.models import Spec
from rue.patching.runtime import PatchHandle
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
                Spec,
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
        self._patch_handles: list[PatchHandle] = []

    @property
    def cached_identities(self) -> dict[ResourceSpec, Any]:
        """Return a shallow copy of the identity-to-value cache."""
        return dict(self._cache)

    def direct_dependencies_for(
        self, identity: ResourceSpec
    ) -> list[ResourceSpec]:
        """Return direct resource dependencies captured during resolution."""
        return list(self._shared_dependency_graph.get(identity, []))

    def autouse_names(self, request_path: Path | None) -> tuple[str, ...]:
        """Return autouse resource names selected for a request path."""
        return tuple(
            definition.spec.locator.function_name
            for definition in self._registry.autouse(request_path)
        )

    async def resolve_autouse(
        self,
        consumer_spec: Spec,
        *,
        apply_injection_hook: bool = True,
    ) -> tuple[str, ...]:
        """Resolve autouse resources selected for a request path."""
        names = self.autouse_names(consumer_spec.locator.module_path)
        for name in names:
            await self.resolve(
                name,
                consumer_spec=consumer_spec,
                apply_injection_hook=apply_injection_hook,
            )
        return names

    @contextlib.contextmanager
    def open_transaction(
        self,
        *,
        consumer_spec: Spec,
        provider_spec: Spec,
    ) -> Iterator[None]:
        """Bind consumer/provider attribution for resolver-owned work."""
        with ResourceTransactionContext(
            consumer_spec=consumer_spec,
            provider_spec=provider_spec,
            resolver=self,
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

    def collect_dependency_closure(
        self,
        names: tuple[str, ...],
        *,
        consumer_spec: Spec,
    ) -> tuple[ResourceSpec, ...]:
        """Return the selected transitive resource closure for a consumer."""
        request_path = consumer_spec.locator.module_path
        connected: dict[str, ResourceSpec] = {}

        def sort_key(spec: ResourceSpec) -> tuple[int, str, str, str]:
            return (
                {"run": 0, "module": 1, "test": 2}.get(
                    spec.scope.value, 99
                ),
                spec.locator.function_name,
                ""
                if spec.locator.module_path is None
                else str(spec.locator.module_path),
                ""
                if spec.locator.module_path is None
                else str(spec.locator.module_path.parent),
            )

        def visit(name: str, path: tuple[ResourceSpec, ...]) -> None:
            definition = self._registry.select(name, request_path).definition
            identity = definition.spec

            if identity in path:
                cycle = " -> ".join(
                    (
                        f"{key.scope.value}:{key.locator.function_name}"
                        if key.locator.module_path is None
                        else (
                            f"{key.scope.value}:{key.locator.function_name}"
                            f"@{key.locator.module_path.parent}"
                        )
                    )
                    for key in (*path, identity)
                )
                raise RuntimeError(
                    f"Circular resource dependency detected: {cycle}"
                )

            if identity.snapshot_key in connected:
                return

            connected[identity.snapshot_key] = identity
            for dependency in identity.dependencies:
                visit(dependency, (*path, identity))

        for name in names:
            visit(name, ())

        return tuple(sorted(connected.values(), key=sort_key))

    async def resolve(
        self,
        name: str,
        *,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
    ) -> Any:
        """Resolve one resource for the given consumer spec."""
        return await self._resolve(
            name,
            request_spec=consumer_spec,
            consumer_spec=consumer_spec,
            apply_injection_hook=apply_injection_hook,
        )

    async def _resolve(
        self,
        name: str,
        *,
        request_spec: Spec,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
    ) -> Any:
        request_path = request_spec.locator.module_path
        definition = self._registry.select(name, request_path).definition
        identity = definition.spec
        scope = identity.scope

        path = _RESOLUTION_PATH.get()
        if identity in path:
            cycle = " -> ".join(
                (
                    f"{key.scope.value}:{key.locator.function_name}"
                    if key.locator.module_path is None
                    else (
                        f"{key.scope.value}:{key.locator.function_name}"
                        f"@{key.locator.module_path.parent}"
                    )
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
            if isinstance(consumer_spec, ResourceSpec):
                direct = self._shared_dependency_graph.get(consumer_spec)
                if direct is None:
                    direct = self._shared_dependency_graph[consumer_spec] = []
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
                            request_spec=request_spec,
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
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
    ) -> dict[str, Any]:
        """Resolve missing parameters into a kwargs dictionary."""
        kwargs = dict(resolved_params)
        for param in unresolved_params:
            kwargs[param] = await self.resolve(
                param,
                consumer_spec=consumer_spec,
                apply_injection_hook=apply_injection_hook,
            )
        return kwargs

    def fork_for_test(self) -> "ResourceResolver":
        """Create a child resolver for isolated TEST-scope execution."""
        child = ResourceResolver(
            self._registry,
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
        teardowns: Sequence[
            tuple[
                ResourceSpec,
                LoadedResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
                Spec,
            ]
        ],
    ) -> list[Exception]:
        teardown_errors: list[Exception] = []

        for key, definition, generator, consumer_spec in reversed(teardowns):
            with self.open_transaction(
                consumer_spec=consumer_spec,
                provider_spec=key,
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
                            f"'{key.locator.function_name}': {e}"
                        )
                    )

                if key in self._cache:
                    try:
                        await self._apply_hook(
                            definition.on_teardown,
                            key.locator.function_name,
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
        matching: list[
            tuple[
                ResourceSpec,
                LoadedResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
                Spec,
            ]
        ] = []
        to_keep: list[
            tuple[
                ResourceSpec,
                LoadedResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
                Spec,
            ]
        ] = []

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
        resources: Sequence[str] | Sequence[ResourceSpec],
        *,
        consumer_spec: Spec,
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
            request_locator=consumer_spec.locator,
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
        self._sync_graph = SyncGraph(actor_id=snapshot.sync_actor_id)

        for identity in snapshot.resolution_order:
            if identity in self._cache:
                continue
            definition = self._registry.select(
                identity.locator.function_name,
                snapshot.request_locator.module_path,
            ).definition
            await self._resolve_uncached(
                name=identity.locator.function_name,
                definition=definition,
                cache_key=identity,
                request_spec=consumer_spec,
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
                    dependencies=tuple(
                        d.locator.function_name for d in dependencies
                    ),
                )
                for identity, dependencies in closure.items()
                if identity.sync
            ]
        if all(isinstance(spec, ResourceSpec) for spec in resource_items):
            specs = cast("list[ResourceSpec]", resource_items)
            return [
                replace(
                    identity,
                    dependencies=tuple(
                        dependency.locator.function_name
                        for dependency in self._shared_dependency_graph.get(
                            identity,
                            (),
                        )
                    ),
                )
                for identity in specs
                if identity.sync
            ]
        msg = "resources must be list[str] or list[ResourceSpec]"
        raise TypeError(msg)

    async def _resolve_uncached(
        self,
        *,
        name: str,
        definition: LoadedResourceDef,
        cache_key: ResourceSpec,
        request_spec: Spec,
        consumer_spec: Spec,
    ) -> Any:
        with self.open_transaction(
            consumer_spec=consumer_spec,
            provider_spec=cache_key,
        ):
            kwargs = {
                dependency: await self._resolve(
                    dependency,
                    request_spec=request_spec,
                    consumer_spec=cache_key,
                )
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
                            (
                                cache_key,
                                definition,
                                async_generator,
                                consumer_spec,
                            )
                        )
                case LoadedResourceDef(is_generator=True):
                    generator = cast(
                        "Generator[Any, None, None]", definition.fn(**kwargs)
                    )
                    value = next(generator)
                    if not self._shadow_mode:
                        self._teardowns.append(
                            (cache_key, definition, generator, consumer_spec)
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
            msg = (
                f"Hook {hook.__name__} failed for resource "
                f"'{resource_name}': {e}"
            )
            raise RuntimeError(
                msg
            ) from e
        return value

    @staticmethod
    def _collect_snapshot_closure(
        resource_names: list[str],
        cache: dict[ResourceSpec, Any],
        dep_graph: dict[ResourceSpec, list[ResourceSpec]],
    ) -> dict[ResourceSpec, list[ResourceSpec]]:
        """Expand names into the dependency closure for a transfer snapshot."""
        name_to_identity = {
            identity.locator.function_name: identity for identity in cache
        }
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
        identity_map = {
            identity.locator.function_name: identity
            for identity in identities
        }
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
            resolved = {identity.locator.function_name for identity in order}
            unresolved = set(identity_map) - resolved
            msg = f"Circular dependency in snapshot resources: {unresolved}"
            raise RuntimeError(msg)

        return order
