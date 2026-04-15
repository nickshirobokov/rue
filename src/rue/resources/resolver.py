"""Resource system for dependency injection."""

import asyncio
import inspect
from collections.abc import AsyncGenerator, Generator
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_RESOURCE_CONSUMER_KIND,
    CURRENT_RESOURCE_PROVIDER,
    CURRENT_RESOURCE_RESOLVER,
    CURRENT_TEST,
    bind,
)
from rue.resources.models import ResourceDef, ResourceIdentity, Scope
from rue.resources.registry import ResourceRegistry


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
        self._shared_creation_locks: dict[ResourceIdentity, asyncio.Lock] = (
            parent._shared_creation_locks if parent is not None else {}
        )
        self._shared_dependency_graph: dict[
            ResourceIdentity, list[ResourceIdentity]
        ] = (
            parent._shared_dependency_graph if parent is not None else {}
        )

    def _owner_resolver_for_scope(self, scope: Scope) -> "ResourceResolver":
        if scope in {Scope.SUITE, Scope.SESSION} and self._parent is not None:
            return self._parent._owner_resolver_for_scope(scope)
        return self

    @staticmethod
    def _cycle_label(key: ResourceIdentity) -> str:
        if key.provider_dir is None:
            return f"{key.scope.value}:{key.name}"
        return f"{key.scope.value}:{key.name}@{key.provider_dir}"

    @staticmethod
    def _request_path() -> Path | None:
        test_ctx = CURRENT_TEST.get()
        if test_ctx is None:
            return None
        return test_ctx.item.spec.module_path.resolve()

    async def _apply_on_injection(
        self,
        definition: ResourceDef,
        name: str,
        value: Any,
    ) -> Any:
        if definition.on_injection:
            try:
                value = definition.on_injection(value)
                if inspect.iscoroutine(value):
                    value = await value
            except Exception as e:
                raise RuntimeError(
                    f"Hook {definition.on_injection.__name__} failed for resource '{name}': {e}"
                ) from e
        return value

    async def _resolve_uncached(
        self,
        *,
        name: str,
        definition: ResourceDef,
        cache_key: ResourceIdentity,
    ) -> Any:
        kwargs = {}
        with (
            bind(CURRENT_RESOURCE_CONSUMER, name),
            bind(CURRENT_RESOURCE_CONSUMER_KIND, "resource"),
            bind(CURRENT_RESOURCE_PROVIDER, definition),
            bind(CURRENT_RESOURCE_RESOLVER, self),
        ):
            for dependency in definition.dependencies:
                kwargs[dependency] = await self.resolve(dependency)

        with (
            bind(CURRENT_RESOURCE_PROVIDER, definition),
            bind(CURRENT_RESOURCE_RESOLVER, self),
        ):
            if definition.is_async_generator:
                generator = definition.fn(**kwargs)
                value = await generator.__anext__()
                self._register_teardown(cache_key, definition, generator)
            elif definition.is_generator:
                generator = definition.fn(**kwargs)
                value = next(generator)
                self._register_teardown(cache_key, definition, generator)
            elif definition.is_async:
                value = await definition.fn(**kwargs)
            else:
                value = definition.fn(**kwargs)

            if definition.on_resolve:
                try:
                    value = definition.on_resolve(value)
                    if inspect.iscoroutine(value):
                        value = await value
                except Exception as e:
                    raise RuntimeError(
                        f"Hook {definition.on_resolve.__name__} failed for resource '{name}': {e}"
                    ) from e

        self._cache[cache_key] = value
        if definition.identity.scope in {Scope.SUITE, Scope.SESSION} and self._parent:
            self._parent._cache[cache_key] = value
        return value

    def fork_for_case(self) -> "ResourceResolver":
        """Create a child resolver for isolated CASE-scope execution."""
        child = ResourceResolver(self._registry, parent=self)
        for key, value in self._cache.items():
            if key.scope in {Scope.SUITE, Scope.SESSION}:
                child._cache[key] = value
        return child

    def _register_teardown(
        self,
        key: ResourceIdentity,
        definition: ResourceDef,
        generator: Generator[Any, None, None] | AsyncGenerator[Any, None],
    ) -> None:
        if key.scope in {Scope.SUITE, Scope.SESSION} and self._parent:
            self._parent._register_teardown(key, definition, generator)
            return
        self._teardowns.append((key, definition, generator))

    def _record_dependency(
        self,
        parent: ResourceIdentity,
        dependency: ResourceIdentity,
    ) -> None:
        direct = self._shared_dependency_graph.setdefault(parent, [])
        if dependency not in direct:
            direct.append(dependency)

    def direct_dependencies_for(
        self, identity: ResourceIdentity
    ) -> list[ResourceIdentity]:
        return list(self._shared_dependency_graph.get(identity, []))

    async def resolve(self, name: str) -> Any:
        selected = self._registry.select(name, self._request_path())
        definition = selected.definition
        cache_key = definition.identity

        path = _RESOLUTION_PATH.get()
        if cache_key in path:
            cycle = " -> ".join(
                self._cycle_label(key) for key in (*path, cache_key)
            )
            raise RuntimeError(
                f"Circular resource dependency detected: {cycle}"
            )

        token = _RESOLUTION_PATH.set((*path, cache_key))
        try:
            owner = self._owner_resolver_for_scope(definition.identity.scope)
            parent = CURRENT_RESOURCE_PROVIDER.get()
            if parent is not None:
                self._record_dependency(parent.identity, cache_key)

            if cache_key in owner._cache:
                value = owner._cache[cache_key]
            elif definition.identity.scope in {Scope.SUITE, Scope.SESSION}:
                lock = owner._shared_creation_locks.setdefault(
                    cache_key, asyncio.Lock()
                )
                async with lock:
                    if cache_key in owner._cache:
                        value = owner._cache[cache_key]
                    else:
                        value = await owner._resolve_uncached(
                            name=name,
                            definition=definition,
                            cache_key=cache_key,
                        )
            else:
                value = await owner._resolve_uncached(
                    name=name,
                    definition=definition,
                    cache_key=cache_key,
                )

            if owner is not self and cache_key in owner._cache:
                self._cache[cache_key] = owner._cache[cache_key]

            with (
                bind(CURRENT_RESOURCE_PROVIDER, definition),
                bind(CURRENT_RESOURCE_RESOLVER, owner),
            ):
                return await self._apply_on_injection(
                    definition, name, value
                )
        finally:
            _RESOLUTION_PATH.reset(token)

    async def resolve_many(self, names: list[str]) -> dict[str, Any]:
        return {name: await self.resolve(name) for name in names}

    async def teardown(self) -> None:
        teardown_errors: list[Exception] = []

        for key, definition, generator in reversed(self._teardowns):
            with (
                bind(CURRENT_RESOURCE_PROVIDER, definition),
                bind(CURRENT_RESOURCE_RESOLVER, self),
            ):
                try:
                    if isinstance(generator, AsyncGenerator):
                        try:
                            await generator.__anext__()
                        except StopAsyncIteration:
                            pass
                    else:
                        try:
                            next(generator)
                        except StopIteration:
                            pass
                except Exception as e:
                    teardown_errors.append(
                        RuntimeError(
                            f"Generator teardown failed for resource '{key.name}': {e}"
                        )
                    )

                if definition.on_teardown and key in self._cache:
                    try:
                        result = definition.on_teardown(self._cache[key])
                        if inspect.iscoroutine(result):
                            await result
                    except Exception as e:
                        teardown_errors.append(
                            RuntimeError(
                                f"Hook {definition.on_teardown.__name__} failed for resource '{key.name}': {e}"
                            )
                        )
        self._teardowns.clear()

        if teardown_errors:
            if len(teardown_errors) == 1:
                raise RuntimeError(teardown_errors[0])
            raise ExceptionGroup("Teardown errors occurred", teardown_errors)

    async def teardown_scope(self, scope: Scope) -> None:
        """Teardown only resources matching the given scope."""
        owner = self._owner_resolver_for_scope(scope)
        teardown_errors: list[Exception] = []
        to_keep: list[
            tuple[
                ResourceIdentity,
                ResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
            ]
        ] = []

        for key, definition, generator in reversed(owner._teardowns):
            if key.scope != scope:
                to_keep.append((key, definition, generator))
                continue
            with (
                bind(CURRENT_RESOURCE_PROVIDER, definition),
                bind(CURRENT_RESOURCE_RESOLVER, owner),
            ):
                try:
                    if isinstance(generator, AsyncGenerator):
                        try:
                            await generator.__anext__()
                        except StopAsyncIteration:
                            pass
                    else:
                        try:
                            next(generator)
                        except StopIteration:
                            pass
                except Exception as e:
                    teardown_errors.append(
                        RuntimeError(
                            f"Generator teardown failed for resource '{key.name}': {e}"
                        )
                    )

                if definition.on_teardown and key in owner._cache:
                    try:
                        result = definition.on_teardown(owner._cache[key])
                        if inspect.iscoroutine(result):
                            await result
                    except Exception as e:
                        teardown_errors.append(
                            RuntimeError(
                                f"Hook {definition.on_teardown.__name__} failed for resource '{key.name}': {e}"
                            )
                        )
            owner._cache.pop(key, None)

        owner._teardowns = list(reversed(to_keep))

        for key in [key for key in owner._cache if key.scope == scope]:
            owner._cache.pop(key, None)

        if teardown_errors:
            if len(teardown_errors) == 1:
                raise RuntimeError(teardown_errors[0])
            raise ExceptionGroup("Teardown errors occurred", teardown_errors)
