"""Resource system for dependency injection."""

import asyncio
import inspect
from collections import deque
from collections.abc import AsyncGenerator, Generator
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
    ResourceBlueprint,
    LoadedResourceDef,
    ResourceSpec,
    Scope,
)
from rue.resources.registry import ResourceRegistry
from rue.resources.snapshot import SnapshotApplier, SnapshotExporter


_RESOLUTION_PATH: ContextVar[tuple[ResourceSpec, ...]] = ContextVar(
    "resource_resolution_path",
    default=(),
)


class ResourceResolver:
    """Resolves and caches resources for test execution."""

    def __init__(
        self,
        registry: ResourceRegistry,
        *,
        parent: "ResourceResolver | None" = None,
        shadow_mode: bool = False,
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
        self._pending: dict[ResourceSpec, asyncio.Task[Any]] = {}
        self._shared_dependency_graph: dict[
            ResourceSpec, list[ResourceSpec]
        ] = parent._shared_dependency_graph if parent is not None else {}
        self._shadow_mode = shadow_mode
        self._snapshot_object_ids: dict[int, int] = {}
        self._snapshot_path_ids: dict[str, int] = {}
        self._snapshot_next_id = 1

    @property
    def cached_identities(self) -> dict[ResourceSpec, Any]:
        """Return a shallow copy of the identity-to-value cache."""
        return dict(self._cache)

    @property
    def dependency_graph(self) -> dict[ResourceSpec, list[ResourceSpec]]:
        """Return a shallow copy of the shared dependency graph."""
        return dict(self._shared_dependency_graph)

    def direct_dependencies_for(
        self, identity: ResourceSpec
    ) -> list[ResourceSpec]:
        return list(self._shared_dependency_graph.get(identity, []))

    async def resolve(self, name: str) -> Any:
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
                created = pending is None
                if created:
                    pending = owner._pending[identity] = (
                        asyncio.get_running_loop().create_future()
                    )
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
                        del owner._pending[identity]
                else:
                    try:
                        value = await pending
                    finally:
                        if pending.cancelled():
                            owner._pending.pop(identity, None)

            if owner is not self:
                self._cache[identity] = value

            with (
                bind(CURRENT_RESOURCE_PROVIDER, definition),
                bind(CURRENT_RESOURCE_RESOLVER, owner),
            ):
                return await self._apply_hook(
                    definition.on_injection, name, value
                )
        finally:
            _RESOLUTION_PATH.reset(token)

    async def resolve_many(self, names: list[str]) -> dict[str, Any]:
        return {name: await self.resolve(name) for name in names}

    def fork_for_test(self) -> "ResourceResolver":
        """Create a child resolver for isolated TEST-scope execution."""
        child = ResourceResolver(self._registry, parent=self)
        child._cache = {
            key: value
            for key, value in self._cache.items()
            if key.scope is not Scope.TEST
        }
        child._snapshot_object_ids = dict(self._snapshot_object_ids)
        child._snapshot_path_ids = dict(self._snapshot_path_ids)
        child._snapshot_next_id = self._snapshot_next_id
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
                            cast(AsyncGenerator[Any, None], generator), None
                        )
                    else:
                        next(
                            cast(Generator[Any, None, None], generator), None
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

    def build_blueprint(
        self,
        resource_names: list[str],
        request_path: Path | None = None,
    ) -> ResourceBlueprint:
        """Build a transfer blueprint for the given resources."""
        closure = self._collect_blueprint_closure(
            resource_names, self._cache, self._shared_dependency_graph
        )
        identities = [
            replace(
                identity,
                dependencies=tuple(d.name for d in dependencies),
            )
            for identity, dependencies in closure.items()
        ]
        resolution_order = self._topological_sort_blueprint_identities(
            identities
        )
        root_map = {
            identity.snapshot_key: self._cache[identity]
            for identity in identities
        }
        exporter = SnapshotExporter(
            known_ids=self._snapshot_object_ids,
            known_paths=self._snapshot_path_ids,
            next_id=self._snapshot_next_id,
        )
        root_ids, nodes, ignored_paths = exporter.export_roots(root_map)
        self._snapshot_object_ids = exporter.object_ids
        self._snapshot_path_ids = exporter.path_ids
        self._snapshot_next_id = exporter.next_id
        return ResourceBlueprint(
            res_specs=tuple(identities),
            request_path=(str(request_path) if request_path else None),
            root_ids=root_ids,
            nodes=nodes,
            ignored_paths=ignored_paths,
            resolution_order=tuple(resolution_order),
        )

    @classmethod
    async def build_from_blueprint(
        cls,
        blueprint: ResourceBlueprint,
        registry: ResourceRegistry,
    ) -> "ResourceResolver":
        resolver = cls(registry, shadow_mode=True)
        request_path = (
            Path(blueprint.request_path) if blueprint.request_path else None
        )

        for identity in blueprint.resolution_order:
            definition = registry.select(identity.name, request_path).definition
            await resolver._resolve_uncached(
                name=identity.name,
                definition=definition,
                cache_key=identity,
            )
        resolver.apply_snapshot(blueprint)
        return resolver

    def snapshot_blueprint(
        self,
        identities: tuple[ResourceSpec, ...],
        request_path: Path | None = None,
    ) -> ResourceBlueprint:
        identities_with_dependencies = tuple(
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
            for identity in identities
        )
        root_map = {
            identity.snapshot_key: self._cache[identity]
            for identity in identities
            if identity in self._cache
        }
        exporter = SnapshotExporter(
            known_ids=self._snapshot_object_ids,
            known_paths=self._snapshot_path_ids,
            next_id=self._snapshot_next_id,
        )
        root_ids, nodes, ignored_paths = exporter.export_roots(root_map)
        self._snapshot_object_ids = exporter.object_ids
        self._snapshot_path_ids = exporter.path_ids
        self._snapshot_next_id = exporter.next_id
        return ResourceBlueprint(
            res_specs=identities_with_dependencies,
            request_path=(str(request_path) if request_path else None),
            root_ids=root_ids,
            nodes=nodes,
            ignored_paths=ignored_paths,
            resolution_order=identities_with_dependencies,
        )

    def snapshot_payload(self, blueprint: ResourceBlueprint) -> dict[str, Any]:
        return {
            "root_ids": dict(blueprint.root_ids),
            "nodes": {node_id: dict(node) for node_id, node in blueprint.nodes.items()},
            "ignored_paths": {
                root_key: list(paths)
                for root_key, paths in blueprint.ignored_paths.items()
            },
        }

    def apply_snapshot(self, blueprint: ResourceBlueprint | dict[str, Any]) -> None:
        payload = (
            self.snapshot_payload(blueprint)
            if isinstance(blueprint, ResourceBlueprint)
            else blueprint
        )
        roots = {
            identity.snapshot_key: self._cache.get(identity)
            for identity in self._cache
        }
        applier = SnapshotApplier(
            payload,
            object_ids=self._snapshot_object_ids,
        )
        patched_roots = applier.apply_roots(roots)
        self._snapshot_object_ids = applier.object_ids
        self._snapshot_next_id = max(
            applier.nodes,
            default=self._snapshot_next_id - 1,
        ) + 1
        key_to_identity = {
            identity.snapshot_key: identity for identity in self._cache
        }
        for root_key, value in patched_roots.items():
            identity = key_to_identity.get(root_key)
            if identity is None:
                continue
            self._cache[identity] = value

    def _owner_resolver_for_scope(self, scope: Scope) -> "ResourceResolver":
        if scope is not Scope.TEST and self._parent is not None:
            return self._parent._owner_resolver_for_scope(scope)
        return self

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
                    generator = cast(
                        AsyncGenerator[Any, None], definition.fn(**kwargs)
                    )
                    value = await anext(generator)
                    if not self._shadow_mode:
                        self._teardowns.append(
                            (cache_key, definition, generator)
                        )
                case LoadedResourceDef(is_generator=True):
                    generator = cast(
                        Generator[Any, None, None], definition.fn(**kwargs)
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
    def _collect_blueprint_closure(
        resource_names: list[str],
        cache: dict[ResourceSpec, Any],
        dep_graph: dict[ResourceSpec, list[ResourceSpec]],
    ) -> dict[ResourceSpec, list[ResourceSpec]]:
        """Expand resource names into a full dependency closure."""
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
    def _topological_sort_blueprint_identities(
        identities: list[ResourceSpec],
    ) -> list[ResourceSpec]:
        """Topologically sort blueprint identities for worker resolution."""
        identity_map = {identity.name: identity for identity in identities}
        if not identity_map:
            return []

        in_degree = dict.fromkeys(identity_map, 0)
        dependents: dict[str, list[str]] = {
            name: [] for name in identity_map
        }

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
            msg = f"Circular dependency in blueprint resources: {unresolved}"
            raise RuntimeError(msg)

        return order
