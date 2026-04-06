"""Resource system for dependency injection."""

import asyncio
import inspect
from collections.abc import AsyncGenerator, Generator
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_TEST,
    bind,
)
from rue.resources.registry import ResourceDef, ResourceRegistry, Scope


@dataclass(frozen=True, slots=True)
class ResourceKey:
    """Cache and resolution identity for a resource provider."""

    scope: Scope
    name: str
    provider_dir: Path | None = None


_RESOLUTION_PATH: ContextVar[tuple[ResourceKey, ...]] = ContextVar(
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
        self._cache: dict[ResourceKey, Any] = {}
        self._teardowns: list[
            tuple[
                ResourceKey,
                ResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
            ]
        ] = []
        self._parent = parent
        self._shared_creation_locks: dict[ResourceKey, asyncio.Lock] = (
            parent._shared_creation_locks if parent is not None else {}
        )

    def _owner_resolver_for_scope(self, scope: Scope) -> "ResourceResolver":
        if scope in {Scope.SUITE, Scope.SESSION} and self._parent is not None:
            return self._parent._owner_resolver_for_scope(scope)
        return self

    @staticmethod
    def _cycle_label(key: ResourceKey) -> str:
        if key.provider_dir is None:
            return f"{key.scope.value}:{key.name}"
        return f"{key.scope.value}:{key.name}@{key.provider_dir}"

    @staticmethod
    def _request_path() -> Path | None:
        test_ctx = CURRENT_TEST.get()
        if test_ctx is None:
            return None
        return test_ctx.item.module_path.resolve()

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
        cache_key: ResourceKey,
    ) -> Any:
        kwargs = {}
        with bind(CURRENT_RESOURCE_CONSUMER, name):
            for dependency in definition.dependencies:
                kwargs[dependency] = await self.resolve(dependency)

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
        if definition.scope in {Scope.SUITE, Scope.SESSION} and self._parent:
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
        key: ResourceKey,
        definition: ResourceDef,
        generator: Generator[Any, None, None] | AsyncGenerator[Any, None],
    ) -> None:
        if key.scope in {Scope.SUITE, Scope.SESSION} and self._parent:
            self._parent._register_teardown(key, definition, generator)
            return
        self._teardowns.append((key, definition, generator))

    async def resolve(self, name: str) -> Any:
        selected = self._registry.select(name, self._request_path())
        definition = selected.definition
        cache_key = ResourceKey(
            scope=definition.scope,
            name=name,
            provider_dir=selected.provider_dir,
        )

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
            owner = self._owner_resolver_for_scope(definition.scope)

            if cache_key in owner._cache:
                value = owner._cache[cache_key]
            elif definition.scope in {Scope.SUITE, Scope.SESSION}:
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

            return await self._apply_on_injection(definition, name, value)
        finally:
            _RESOLUTION_PATH.reset(token)

    async def resolve_many(self, names: list[str]) -> dict[str, Any]:
        return {name: await self.resolve(name) for name in names}

    async def teardown(self) -> None:
        teardown_errors: list[Exception] = []

        for key, definition, generator in reversed(self._teardowns):
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
                ResourceKey,
                ResourceDef,
                Generator[Any, None, None] | AsyncGenerator[Any, None],
            ]
        ] = []

        for key, definition, generator in reversed(owner._teardowns):
            if key.scope != scope:
                to_keep.append((key, definition, generator))
                continue
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
