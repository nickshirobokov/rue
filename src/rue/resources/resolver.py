"""Resource system for dependency injection."""

import asyncio
import inspect
from collections import deque
from collections.abc import AsyncGenerator, Generator
from contextvars import ContextVar
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
    ResourceDef,
    ResourceIdentity,
    ResourceTransferEntry,
    Scope,
    TransferStrategy,
)
from rue.resources.registry import ResourceRegistry
from rue.resources.serialization import (
    check_serializable,
    deserialize_value,
    serialize_value,
)


_RESOLUTION_PATH: ContextVar[tuple[ResourceIdentity, ...]] = ContextVar(
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
    ) -> None:
        self._registry = registry
        self._cache: dict[ResourceIdentity, Any] = {}
        self._teardowns: list[
            tuple[
                ResourceIdentity,
                ResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
            ]
        ] = []
        self._parent = parent
        self._pending: dict[ResourceIdentity, asyncio.Task[Any]] = {}
        self._shared_dependency_graph: dict[
            ResourceIdentity, list[ResourceIdentity]
        ] = parent._shared_dependency_graph if parent is not None else {}

    @property
    def cached_identities(self) -> dict[ResourceIdentity, Any]:
        """Return a shallow copy of the identity-to-value cache."""
        return dict(self._cache)

    @property
    def dependency_graph(self) -> dict[ResourceIdentity, list[ResourceIdentity]]:
        """Return a shallow copy of the shared dependency graph."""
        return dict(self._shared_dependency_graph)

    def direct_dependencies_for(
        self, identity: ResourceIdentity
    ) -> list[ResourceIdentity]:
        return list(self._shared_dependency_graph.get(identity, []))

    async def resolve(self, name: str) -> Any:
        test_ctx = CURRENT_TEST.get()
        request_path = (
            None
            if test_ctx is None
            else test_ctx.item.spec.module_path.resolve()
        )
        definition = self._registry.select(name, request_path).definition
        identity = definition.identity
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
                direct = self._shared_dependency_graph.get(parent.identity)
                if direct is None:
                    direct = self._shared_dependency_graph[parent.identity] = []
                if identity not in direct:
                    direct.append(identity)

            value = owner._cache.get(identity, missing)
            if value is missing:
                pending = owner._pending.get(identity)
                created = pending is None
                if created:
                    pending = owner._pending[identity] = asyncio.create_task(
                        owner._resolve_uncached(
                            name=name,
                            definition=definition,
                            cache_key=identity,
                        )
                    )
                try:
                    value = await pending
                finally:
                    if created:
                        del owner._pending[identity]

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
        return child

    async def teardown(self) -> None:
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
        owner = self._owner_resolver_for_scope(scope)
        matching: list[
            tuple[
                ResourceIdentity,
                ResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
            ]
        ] = []
        to_keep: list[
            tuple[
                ResourceIdentity,
                ResourceDef,
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
        entries = self._build_blueprint_entries(closure, self._cache)
        resolution_order = self._topological_sort_blueprint_entries(entries)
        return ResourceBlueprint(
            entries=tuple(entries),
            resolution_order=tuple(resolution_order),
            request_path=(str(request_path) if request_path else None),
        )

    @classmethod
    async def build_from_blueprint(
        cls,
        blueprint: ResourceBlueprint,
        registry: ResourceRegistry,
    ) -> "ResourceResolver":
        resolver = cls(registry)
        request_path = (
            Path(blueprint.request_path) if blueprint.request_path else None
        )

        for entry in blueprint.entries:
            if (
                entry.strategy == TransferStrategy.SERIALIZE
                and entry.serialized_value is not None
            ):
                resolver._cache[entry.identity] = deserialize_value(
                    entry.serialized_value
                )

        for identity in blueprint.resolution_order:
            definition = registry.select(identity.name, request_path).definition
            await resolver._resolve_uncached(
                name=identity.name,
                definition=definition,
                cache_key=identity,
            )
        return resolver

    def _owner_resolver_for_scope(self, scope: Scope) -> "ResourceResolver":
        if scope is not Scope.TEST and self._parent is not None:
            return self._parent._owner_resolver_for_scope(scope)
        return self

    async def _resolve_uncached(
        self,
        *,
        name: str,
        definition: ResourceDef,
        cache_key: ResourceIdentity,
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
                    for dependency in definition.dependencies
                }

            match definition:
                case ResourceDef(is_async_generator=True):
                    generator = cast(
                        AsyncGenerator[Any, None], definition.fn(**kwargs)
                    )
                    value = await anext(generator)
                    self._teardowns.append(
                        (cache_key, definition, generator)
                    )
                case ResourceDef(is_generator=True):
                    generator = cast(
                        Generator[Any, None, None], definition.fn(**kwargs)
                    )
                    value = next(generator)
                    self._teardowns.append(
                        (cache_key, definition, generator)
                    )
                case ResourceDef(is_async=True):
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
        cache: dict[ResourceIdentity, Any],
        dep_graph: dict[ResourceIdentity, list[ResourceIdentity]],
    ) -> dict[ResourceIdentity, list[ResourceIdentity]]:
        """Expand resource names into a full dependency closure."""
        name_to_identity = {identity.name: identity for identity in cache}
        closure: dict[ResourceIdentity, list[ResourceIdentity]] = {}
        visited: set[ResourceIdentity] = set()
        queue: deque[ResourceIdentity] = deque(
            name_to_identity[name]
            for name in resource_names
            if name in name_to_identity
        )

        while queue:
            identity = queue.popleft()
            if identity in visited or identity.scope is Scope.TEST:
                continue
            visited.add(identity)

            dependencies = [
                dependency
                for dependency in dep_graph.get(identity, ())
                if dependency.scope is not Scope.TEST
            ]
            closure[identity] = dependencies
            queue.extend(
                dependency
                for dependency in dependencies
                if dependency not in visited
            )

        return closure

    @staticmethod
    def _build_blueprint_entries(
        closure: dict[ResourceIdentity, list[ResourceIdentity]],
        cache: dict[ResourceIdentity, Any],
    ) -> list[ResourceTransferEntry]:
        """Classify and build transfer entries."""
        entries: list[ResourceTransferEntry] = []

        for identity, dependencies in closure.items():
            serialized_value = None
            try:
                value = cache[identity]
            except KeyError:
                strategy = TransferStrategy.UNKNOWN
            else:
                strategy = (
                    TransferStrategy.SERIALIZE
                    if check_serializable(value)
                    else TransferStrategy.RE_RESOLVE
                )
                if strategy is TransferStrategy.SERIALIZE:
                    serialized_value = serialize_value(value)

            entries.append(
                ResourceTransferEntry(
                    identity=identity,
                    strategy=strategy,
                    serialized_value=serialized_value,
                    dependencies=tuple(dependencies),
                )
            )

        return entries

    @staticmethod
    def _topological_sort_blueprint_entries(
        entries: list[ResourceTransferEntry],
    ) -> list[ResourceIdentity]:
        """Topologically sort RE_RESOLVE and UNKNOWN entries."""
        entry_map = {
            entry.identity: entry
            for entry in entries
            if entry.strategy
            in (TransferStrategy.RE_RESOLVE, TransferStrategy.UNKNOWN)
        }
        if not entry_map:
            return []

        in_degree = dict.fromkeys(entry_map, 0)
        dependents: dict[ResourceIdentity, list[ResourceIdentity]] = {
            identity: [] for identity in entry_map
        }

        for identity, entry in entry_map.items():
            for dependency in entry.dependencies:
                if dependency in entry_map:
                    in_degree[identity] += 1
                    dependents[dependency].append(identity)

        queue: deque[ResourceIdentity] = deque(
            identity
            for identity, degree in in_degree.items()
            if degree == 0
        )
        order: list[ResourceIdentity] = []

        while queue:
            identity = queue.popleft()
            order.append(identity)
            for dependent in dependents[identity]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(entry_map):
            resolved = {identity.name for identity in order}
            unresolved = {identity.name for identity in entry_map} - resolved
            msg = f"Circular dependency in RE_RESOLVE resources: {unresolved}"
            raise RuntimeError(msg)

        return order
