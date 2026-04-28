"""Resource registry and registration APIs."""

import inspect
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.models import Locator, Spec
from rue.resources.models import (
    LoadedResourceDef,
    ResourceGraph,
    ResourceSpec,
    Scope,
)


_RECEIVER_PARAMETER_NAMES = {"self", "cls"}
RESOURCE_SCOPE_PRIORITY = (Scope.TEST, Scope.MODULE, Scope.RUN)
type _ScopedDefinitions = dict[Scope, dict[Path | None, LoadedResourceDef]]
type _SelectionPlan = tuple[
    tuple[tuple[Path, LoadedResourceDef], ...],
    LoadedResourceDef,
]


class ResourceRegistry:
    """Registry of resource definitions and lookup rules."""

    def __init__(self) -> None:
        self._definitions: dict[str, _ScopedDefinitions] = {}
        self._builtin_definitions: dict[str, _ScopedDefinitions] = {}
        self._graph: ResourceGraph | None = None

    @property
    def graph(self) -> ResourceGraph:
        """Return the active compiled resource graph."""
        if self._graph is None:
            raise RuntimeError("Resource graph is not compiled")
        return self._graph

    @graph.setter
    def graph(self, graph: ResourceGraph) -> None:
        self._graph = graph

    def resource[**P, T](
        self,
        fn: Callable[P, T] | None = None,
        *,
        scope: Scope | str = Scope.TEST,
        on_resolve: Callable[[Any], Any] | None = None,
        on_injection: Callable[[Any], Any] | None = None,
        on_teardown: Callable[[Any], Any] | None = None,
        origin_fn: Callable[..., Any] | None = None,
        autouse: bool = False,
        sync: bool = True,
        builtin: bool = False,
    ) -> Any:
        """Register a function as a resource for dependency injection."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            nonlocal scope
            if isinstance(scope, str):
                scope = Scope(scope)

            signature = inspect.signature(fn)
            dependencies = [
                parameter
                for parameter in signature.parameters
                if parameter not in _RECEIVER_PARAMETER_NAMES
            ]
            is_async = inspect.iscoroutinefunction(fn)
            is_async_generator = inspect.isasyncgenfunction(fn)
            is_generator = inspect.isgeneratorfunction(fn)
            filename = (origin_fn or fn).__code__.co_filename
            origin_path = (
                None
                if filename.startswith("<") and filename.endswith(">")
                else Path(filename).resolve()
            )

            definition = LoadedResourceDef(
                spec=ResourceSpec(
                    locator=Locator(
                        module_path=origin_path,
                        function_name=fn.__name__,
                    ),
                    scope=scope,
                    dependencies=tuple(dependencies),
                    autouse=autouse,
                    sync=sync,
                ),
                fn=fn,
                is_async=is_async or is_async_generator,
                is_generator=is_generator,
                is_async_generator=is_async_generator,
                on_resolve=on_resolve,
                on_injection=on_injection,
                on_teardown=on_teardown,
            )
            spec = definition.spec
            by_scope = self._definitions.setdefault(spec.name, {})
            by_path = by_scope.setdefault(spec.scope, {})
            by_path[spec.module_path] = definition
            self._graph = None
            if builtin:
                builtin_by_scope = self._builtin_definitions.setdefault(
                    spec.name,
                    {},
                )
                builtin_by_scope.setdefault(spec.scope, {})[
                    spec.module_path
                ] = definition
            return fn

        if fn is not None:
            return decorator(fn)
        return decorator

    def reset(self) -> None:
        """Reset to builtin registrations only."""
        self._definitions = {
            name: {
                scope: dict(by_path)
                for scope, by_path in by_scope.items()
            }
            for name, by_scope in self._builtin_definitions.items()
        }
        self._graph = None

    def definition(self, spec: ResourceSpec) -> LoadedResourceDef:
        """Return the exact registered definition for a resource identity."""
        definition = (
            self._definitions.get(spec.name, {})
            .get(spec.scope, {})
            .get(spec.module_path)
        )
        if definition is None:
            msg = (
                "Unknown resource identity: "
                f"{spec.scope.value}:{spec.name}"
            )
            if spec.module_path is not None:
                msg = f"{msg}@{spec.module_path}"
            raise ValueError(msg)
        return definition

    def compile_graph(
        self,
        consumers: Mapping[UUID, tuple[Spec, tuple[str, ...]]],
        *,
        autouse_keys: frozenset[UUID] = frozenset(),
    ) -> ResourceGraph:
        """Compile a concrete resource graph for known injection consumers."""
        dependencies_by_spec: dict[ResourceSpec, tuple[ResourceSpec, ...]] = {}
        roots_by_key: dict[UUID, tuple[ResourceSpec, ...]] = {}
        autouse_by_key: dict[UUID, tuple[ResourceSpec, ...]] = {}
        injections_by_key: dict[UUID, dict[str, ResourceSpec]] = {}
        order_by_key: dict[UUID, tuple[ResourceSpec, ...]] = {}
        built: set[ResourceSpec] = set()
        resolving: list[ResourceSpec] = []
        resolving_set: set[ResourceSpec] = set()
        self._graph = None
        autouse_names = tuple(
            sorted(
                name
                for name, by_scope in self._definitions.items()
                if any(
                    definition.spec.autouse
                    for by_path in by_scope.values()
                    for definition in by_path.values()
                )
            )
        )
        dir_cache: dict[Path | None, Path | None] = {None: None}
        select_cache: dict[tuple[str, Path | None], LoadedResourceDef] = {}
        plan_cache: dict[str, _SelectionPlan] = {}
        closure_cache: dict[ResourceSpec, tuple[ResourceSpec, ...]] = {}

        def consumer_dir(consumer: Spec) -> Path | None:
            path = consumer.module_path
            if path not in dir_cache:
                dir_cache[path] = path.resolve().parent
            return dir_cache[path]

        def selection_plan(
            requested_resource: str,
        ) -> _SelectionPlan:
            if requested_resource in plan_cache:
                return plan_cache[requested_resource]
            by_scope = self._definitions.get(requested_resource)
            if by_scope is None:
                msg = f"Unknown resource: {requested_resource}"
                raise ValueError(msg)

            for scope in RESOURCE_SCOPE_PRIORITY:
                by_path = by_scope.get(scope)
                if not by_path:
                    continue

                candidates = [
                    (
                        module_path.parent,
                        len(module_path.parent.parts),
                        index,
                        definition,
                    )
                    for index, (module_path, definition) in enumerate(
                        by_path.items()
                    )
                    if module_path is not None
                ]
                candidates.sort(
                    key=lambda item: (item[1], item[2]),
                    reverse=True,
                )
                compiled = (
                    tuple(
                        (provider_dir, definition)
                        for (
                            provider_dir,
                            _depth,
                            _index,
                            definition,
                        ) in candidates
                    ),
                    next(reversed(by_path.values())),
                )
                plan_cache[requested_resource] = compiled
                return compiled

            msg = f"Unknown resource: {requested_resource}"
            raise ValueError(msg)

        def select_definition(
            consumer: Spec,
            requested_resource: str,
        ) -> LoadedResourceDef:
            directory = consumer_dir(consumer)
            cache_key = (requested_resource, directory)
            if cache_key in select_cache:
                return select_cache[cache_key]

            candidates, fallback = selection_plan(requested_resource)
            if directory is None:
                select_cache[cache_key] = fallback
                return fallback
            for provider_dir, definition in candidates:
                if directory.is_relative_to(provider_dir):
                    select_cache[cache_key] = definition
                    return definition
            select_cache[cache_key] = fallback
            return fallback

        def build(definition: LoadedResourceDef) -> ResourceSpec:
            identity = definition.spec
            if identity in built:
                return identity
            if identity in resolving_set:
                msg = "Circular resource dependency detected"
                raise RuntimeError(msg)

            resolving.append(identity)
            resolving_set.add(identity)
            dependencies = tuple(
                build(
                    select_definition(
                        consumer=identity,
                        requested_resource=dependency,
                    )
                )
                for dependency in identity.dependencies
            )
            resolving.pop()
            resolving_set.remove(identity)
            dependencies_by_spec[identity] = dependencies
            built.add(identity)
            return identity

        def closure(identity: ResourceSpec) -> tuple[ResourceSpec, ...]:
            if identity in closure_cache:
                return closure_cache[identity]

            ordered: list[ResourceSpec] = []
            seen: set[ResourceSpec] = set()
            for dependency in dependencies_by_spec[identity]:
                for dependency_identity in closure(dependency):
                    if dependency_identity in seen:
                        continue
                    seen.add(dependency_identity)
                    ordered.append(dependency_identity)
            ordered.append(identity)
            closure_cache[identity] = compiled = tuple(ordered)
            return compiled

        def order(roots: tuple[ResourceSpec, ...]) -> tuple[ResourceSpec, ...]:
            ordered: list[ResourceSpec] = []
            seen: set[ResourceSpec] = set()
            for root in roots:
                for identity in closure(root):
                    if identity in seen:
                        continue
                    seen.add(identity)
                    ordered.append(identity)
            return tuple(ordered)

        for key, (consumer, resource_names) in consumers.items():
            autouse_specs = (
                tuple(
                    build(definition)
                    for name in autouse_names
                    if (
                        definition := select_definition(
                            consumer=consumer,
                            requested_resource=name,
                        )
                    ).spec.autouse
                )
                if key in autouse_keys
                else ()
            )
            injections = {
                name: build(
                    select_definition(
                        consumer=consumer,
                        requested_resource=name,
                    )
                )
                for name in resource_names
            }
            roots = (*autouse_specs, *injections.values())
            autouse_by_key[key] = autouse_specs
            injections_by_key[key] = injections
            roots_by_key[key] = roots
            order_by_key[key] = order(roots)

        graph = ResourceGraph(
            roots_by_key=roots_by_key,
            autouse_by_key=autouse_by_key,
            injections_by_key=injections_by_key,
            dependencies_by_spec=dependencies_by_spec,
            order_by_key=order_by_key,
        )
        self._graph = graph
        return graph


registry = ResourceRegistry()


def resource[**P, T](
    fn: Callable[P, T] | None = None,
    *,
    scope: Scope | str = Scope.TEST,
    on_resolve: Callable[[Any], Any] | None = None,
    on_injection: Callable[[Any], Any] | None = None,
    on_teardown: Callable[[Any], Any] | None = None,
    origin_fn: Callable[..., Any] | None = None,
    autouse: bool = False,
    sync: bool = True,
) -> Any:
    """Register a function as a resource in the default registry."""
    return registry.resource(
        fn,
        scope=scope,
        on_resolve=on_resolve,
        on_injection=on_injection,
        on_teardown=on_teardown,
        origin_fn=origin_fn,
        autouse=autouse,
        sync=sync,
    )
