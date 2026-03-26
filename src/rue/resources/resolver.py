"""Resource system for dependency injection.

Similar to pytest fixtures, resources provide injectable dependencies
based on parameter name matching.
"""

import asyncio
import inspect
from collections.abc import AsyncGenerator, Callable, Generator
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_TEST,
    bind,
)

P = ParamSpec("P")
T = TypeVar("T")


class Scope(Enum):
    """Resource lifecycle scope."""

    CASE = "case"  # Fresh instance per test
    SUITE = "suite"  # Shared across tests in same file
    SESSION = "session"  # Shared across entire test run


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


@dataclass
class ResourceDef:
    """Definition of a registered resource."""

    name: str
    fn: Callable[..., Any]
    scope: Scope
    is_async: bool
    is_generator: bool
    is_async_generator: bool
    dependencies: list[str] = field(default_factory=list)
    on_resolve: Callable[[Any], Any] | None = None
    on_injection: Callable[[Any], Any] | None = None
    on_teardown: Callable[[Any], Any] | None = None
    origin_path: Path | None = None
    origin_dir: Path | None = None


_registry: dict[str, ResourceDef] = {}
_session_registry: dict[str, list[ResourceDef]] = {}
_builtin_registry: dict[str, ResourceDef] = {}
_builtin_session_registry: dict[str, list[ResourceDef]] = {}


def _resource_origin(fn: Callable[..., Any]) -> tuple[Path | None, Path | None]:
    filename = fn.__code__.co_filename
    if filename.startswith("<") and filename.endswith(">"):
        return None, None

    path = Path(filename).resolve()
    return path, path.parent


def _register_resource(defn: ResourceDef) -> None:
    if defn.scope == Scope.SESSION:
        defs = _session_registry.setdefault(defn.name, [])
        defs.append(defn)

        current = _registry.get(defn.name)
        if current is None or current.scope == Scope.SESSION:
            _registry[defn.name] = defn
        return

    _registry[defn.name] = defn


def resource(
    fn: Callable[P, T] | None = None,
    *,
    scope: Scope | str = Scope.CASE,
    on_resolve: Callable[[Any], Any] | None = None,
    on_injection: Callable[[Any], Any] | None = None,
    on_teardown: Callable[[Any], Any] | None = None,
) -> Any:
    """Register a function as a resource for dependency injection."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        nonlocal scope
        if isinstance(scope, str):
            scope = Scope(scope)

        sig = inspect.signature(fn)
        deps = [p for p in sig.parameters if p != "self"]

        is_async = inspect.iscoroutinefunction(fn)
        is_async_gen = inspect.isasyncgenfunction(fn)
        is_gen = inspect.isgeneratorfunction(fn)
        origin_path, origin_dir = _resource_origin(fn)

        defn = ResourceDef(
            name=fn.__name__,
            fn=fn,
            scope=scope,
            is_async=is_async or is_async_gen,
            is_generator=is_gen,
            is_async_generator=is_async_gen,
            dependencies=deps,
            on_resolve=on_resolve,
            on_injection=on_injection,
            on_teardown=on_teardown,
            origin_path=origin_path,
            origin_dir=origin_dir,
        )
        _register_resource(defn)
        return fn

    if fn is not None:
        return decorator(fn)
    return decorator


def get_registry() -> dict[str, ResourceDef]:
    """Get the global resource registry."""
    return _registry


def register_builtin(name: str) -> None:
    _builtin_registry[name] = _registry[name]
    if name in _session_registry:
        _builtin_session_registry[name] = list(_session_registry[name])


def clear_registry() -> None:
    """Clear all registered resources."""
    _registry.clear()
    _registry.update(_builtin_registry)
    _session_registry.clear()
    _session_registry.update(
        {name: list(defs) for name, defs in _builtin_session_registry.items()}
    )


class ResourceResolver:
    """Resolves and caches resources for test execution."""

    def __init__(
        self,
        registry: dict[str, ResourceDef] | None = None,
        *,
        parent: "ResourceResolver | None" = None,
    ) -> None:
        self._registry = registry if registry is not None else _registry
        self._session_registry = self._resolve_session_registry(
            registry=registry,
            parent=parent,
        )
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

    @staticmethod
    def _resolve_session_registry(
        *,
        registry: dict[str, ResourceDef] | None,
        parent: "ResourceResolver | None",
    ) -> dict[str, list[ResourceDef]]:
        if parent is not None:
            return parent._session_registry
        if registry is None or registry is _registry:
            return _session_registry
        return {
            name: [defn]
            for name, defn in registry.items()
            if defn.scope == Scope.SESSION
        }

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
    def _request_dir() -> Path | None:
        test_ctx = CURRENT_TEST.get()
        if test_ctx is None:
            return None
        return test_ctx.item.module_path.resolve().parent

    def _select_session_definition(
        self, name: str
    ) -> tuple[ResourceDef, ResourceKey]:
        request_dir = self._request_dir()
        selected: ResourceDef | None = None
        selected_depth = -1

        if request_dir is not None:
            for defn in self._session_registry.get(name, []):
                if defn.origin_dir is None or not request_dir.is_relative_to(
                    defn.origin_dir
                ):
                    continue
                depth = len(defn.origin_dir.parts)
                if depth >= selected_depth:
                    selected = defn
                    selected_depth = depth

        if selected is not None:
            return selected, ResourceKey(
                scope=selected.scope,
                name=name,
                provider_dir=selected.origin_dir,
            )

        if name not in self._registry:
            msg = f"Unknown resource: {name}"
            raise ValueError(msg)

        defn = self._registry[name]
        return defn, ResourceKey(scope=defn.scope, name=name)

    def _select_definition(self, name: str) -> tuple[ResourceDef, ResourceKey]:
        if name not in self._registry and name not in self._session_registry:
            msg = f"Unknown resource: {name}"
            raise ValueError(msg)

        defn = self._registry.get(name)
        if defn is not None and defn.scope != Scope.SESSION:
            return defn, ResourceKey(scope=defn.scope, name=name)
        return self._select_session_definition(name)

    async def _apply_on_injection(
        self, defn: ResourceDef, name: str, value: Any
    ) -> Any:
        if defn.on_injection:
            try:
                value = defn.on_injection(value)
                if inspect.iscoroutine(value):
                    value = await value
            except Exception as e:
                raise RuntimeError(
                    f"Hook {defn.on_injection.__name__} failed for resource '{name}': {e}"
                ) from e
        return value

    async def _resolve_uncached(
        self,
        *,
        name: str,
        defn: ResourceDef,
        cache_key: ResourceKey,
    ) -> Any:
        kwargs = {}
        with bind(CURRENT_RESOURCE_CONSUMER, name):
            for dep in defn.dependencies:
                kwargs[dep] = await self.resolve(dep)

        if defn.is_async_generator:
            gen = defn.fn(**kwargs)
            value = await gen.__anext__()
            self._register_teardown(cache_key, defn, gen)
        elif defn.is_generator:
            gen = defn.fn(**kwargs)
            value = next(gen)
            self._register_teardown(cache_key, defn, gen)
        elif defn.is_async:
            value = await defn.fn(**kwargs)
        else:
            value = defn.fn(**kwargs)

        if defn.on_resolve:
            try:
                value = defn.on_resolve(value)
                if inspect.iscoroutine(value):
                    value = await value
            except Exception as e:
                raise RuntimeError(
                    f"Hook {defn.on_resolve.__name__} failed for resource '{name}': {e}"
                ) from e

        self._cache[cache_key] = value
        if defn.scope in {Scope.SUITE, Scope.SESSION} and self._parent:
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
        defn: ResourceDef,
        gen: Generator[Any, None, None] | AsyncGenerator[Any, None],
    ) -> None:
        if key.scope in {Scope.SUITE, Scope.SESSION} and self._parent:
            self._parent._register_teardown(key, defn, gen)
        else:
            self._teardowns.append((key, defn, gen))

    async def resolve(self, name: str) -> Any:
        defn, cache_key = self._select_definition(name)
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
            owner = self._owner_resolver_for_scope(defn.scope)

            if cache_key in owner._cache:
                value = owner._cache[cache_key]
            elif defn.scope in {Scope.SUITE, Scope.SESSION}:
                lock = owner._shared_creation_locks.setdefault(
                    cache_key, asyncio.Lock()
                )
                async with lock:
                    if cache_key in owner._cache:
                        value = owner._cache[cache_key]
                    else:
                        value = await owner._resolve_uncached(
                            name=name,
                            defn=defn,
                            cache_key=cache_key,
                        )
            else:
                value = await owner._resolve_uncached(
                    name=name, defn=defn, cache_key=cache_key
                )

            if owner is not self and cache_key in owner._cache:
                self._cache[cache_key] = owner._cache[cache_key]

            return await self._apply_on_injection(defn, name, value)
        finally:
            _RESOLUTION_PATH.reset(token)

    async def resolve_many(self, names: list[str]) -> dict[str, Any]:
        return {name: await self.resolve(name) for name in names}

    async def teardown(self) -> None:
        teardown_errors: list[Exception] = []

        for key, defn, gen in reversed(self._teardowns):
            try:
                if isinstance(gen, AsyncGenerator):
                    try:
                        await gen.__anext__()
                    except StopAsyncIteration:
                        pass
                else:
                    try:
                        next(gen)
                    except StopIteration:
                        pass
            except Exception as e:
                teardown_errors.append(
                    RuntimeError(
                        f"Generator teardown failed for resource '{key.name}': {e}"
                    )
                )

            if defn.on_teardown and key in self._cache:
                try:
                    result = defn.on_teardown(self._cache[key])
                    if inspect.iscoroutine(result):
                        await result
                except Exception as e:
                    teardown_errors.append(
                        RuntimeError(
                            f"Hook {defn.on_teardown.__name__} failed for resource '{key.name}': {e}"
                        )
                    )
        self._teardowns.clear()

        if teardown_errors:
            if len(teardown_errors) == 1:
                raise RuntimeError(teardown_errors[0])
            raise ExceptionGroup("Teardown errors occurred", teardown_errors)

    async def teardown_scope(self, scope: Scope) -> None:
        remaining = []
        teardown_errors: list[Exception] = []

        for key, defn, gen in reversed(self._teardowns):
            if key.scope == scope:
                try:
                    if isinstance(gen, AsyncGenerator):
                        try:
                            await gen.__anext__()
                        except StopAsyncIteration:
                            pass
                    else:
                        try:
                            next(gen)
                        except StopIteration:
                            pass
                except Exception as e:
                    teardown_errors.append(
                        RuntimeError(
                            f"Generator teardown failed for resource '{key.name}': {e}"
                        )
                    )

                if defn.on_teardown and key in self._cache:
                    try:
                        result = defn.on_teardown(self._cache[key])
                        if inspect.iscoroutine(result):
                            await result
                    except Exception as e:
                        teardown_errors.append(
                            RuntimeError(
                                f"Hook {defn.on_teardown.__name__} failed for resource '{key.name}': {e}"
                            )
                        )
            else:
                remaining.append((key, defn, gen))

        self._teardowns = list(reversed(remaining))

        keys_to_remove = [key for key in self._cache if key.scope == scope]
        for key in keys_to_remove:
            del self._cache[key]

        if teardown_errors:
            if len(teardown_errors) == 1:
                raise RuntimeError(teardown_errors[0])
            raise ExceptionGroup("Teardown errors occurred", teardown_errors)
