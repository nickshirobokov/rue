"""Resource registry and registration APIs."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.context.scopes import Scope
from rue.models import Locator, Spec
from rue.resources.models import (
    LoadedResourceDef,
    ResourceFactoryKind,
    ResourceGraph,
    ResourceSpec,
)


_RECEIVER_PARAMETER_NAMES = {"self", "cls"}
type _DefinitionsByScope = dict[Scope, dict[Path | None, LoadedResourceDef]]
type _ProviderSelectionPlan = tuple[
    tuple[tuple[Path, LoadedResourceDef], ...],
    LoadedResourceDef,
]


class ResourceRegistry:
    """Registry of resource definitions and lookup rules."""

    def __init__(self) -> None:
        self._definitions: dict[str, _DefinitionsByScope] = {}
        self._builtin_definitions: dict[str, _DefinitionsByScope] = {}
        self._graphs_by_execution_id: dict[UUID, ResourceGraph] = {}

    def register_resource[**P, T](
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
            resource_scope = Scope(scope)

            signature = inspect.signature(fn)
            dependencies = [
                parameter
                for parameter in signature.parameters
                if parameter not in _RECEIVER_PARAMETER_NAMES
            ]
            is_async = inspect.iscoroutinefunction(fn)
            is_async_generator = inspect.isasyncgenfunction(fn)
            is_generator = inspect.isgeneratorfunction(fn)
            factory_kind: ResourceFactoryKind
            match (is_async, is_generator, is_async_generator):
                case (_, _, True):
                    factory_kind = ResourceFactoryKind.ASYNC_GENERATOR
                case (_, True, _):
                    factory_kind = ResourceFactoryKind.GENERATOR
                case (True, _, _):
                    factory_kind = ResourceFactoryKind.ASYNC
                case _:
                    factory_kind = ResourceFactoryKind.SYNC
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
                    scope=resource_scope,
                ),
                fn=fn,
                factory_kind=factory_kind,
                dependencies=tuple(dependencies),
                autouse=autouse,
                sync=sync,
                resolve_hook=on_resolve,
                injection_hook=on_injection,
                teardown_hook=on_teardown,
            )
            spec = definition.spec
            by_scope = self._definitions.setdefault(spec.name, {})
            by_path = by_scope.setdefault(spec.scope, {})
            by_path[spec.module_path] = definition
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
        self._graphs_by_execution_id.clear()

    def get_definition(self, spec: ResourceSpec) -> LoadedResourceDef:
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

    def compile_graphs(
        self,
        consumers: Mapping[UUID, tuple[Spec, tuple[str, ...]]],
        *,
        autouse_keys: frozenset[UUID] = frozenset(),
    ) -> dict[UUID, ResourceGraph]:
        """Compile a concrete resource graph for known injection consumers."""
        dependencies_by_resource: dict[
            ResourceSpec, tuple[ResourceSpec, ...]
        ] = {}
        graphs: dict[UUID, ResourceGraph] = {}
        built: set[ResourceSpec] = set()
        resolving: list[ResourceSpec] = []
        resolving_set: set[ResourceSpec] = set()
        autouse_names = tuple(
            sorted(
                name
                for name, by_scope in self._definitions.items()
                if any(
                    definition.autouse
                    for by_path in by_scope.values()
                    for definition in by_path.values()
                )
            )
        )
        dir_cache: dict[Path | None, Path | None] = {None: None}
        select_cache: dict[
            tuple[str, Path | None, tuple[Scope, ...]], LoadedResourceDef
        ] = {}
        plan_cache: dict[tuple[str, Scope], _ProviderSelectionPlan] = {}
        closure_cache: dict[ResourceSpec, tuple[ResourceSpec, ...]] = {}

        def consumer_dir(consumer: Spec) -> Path | None:
            path = consumer.module_path
            if path not in dir_cache and path is not None:
                dir_cache[path] = path.resolve().parent
            return dir_cache[path]

        def selection_plan(
            requested_resource: str,
            scope: Scope,
        ) -> _ProviderSelectionPlan:
            cache_key = (requested_resource, scope)
            if cache_key in plan_cache:
                return plan_cache[cache_key]
            by_scope = self._definitions.get(requested_resource)
            if by_scope is None:
                msg = f"Unknown resource: {requested_resource}"
                raise ValueError(msg)

            by_path = by_scope.get(scope)
            if not by_path:
                msg = f"Unknown resource: {requested_resource}"
                raise ValueError(msg)

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
            plan_cache[cache_key] = compiled
            return compiled

        def available_scopes(requested_resource: str) -> tuple[Scope, ...]:
            by_scope = self._definitions.get(requested_resource)
            if by_scope is None:
                msg = f"Unknown resource: {requested_resource}"
                raise ValueError(msg)
            return tuple(
                scope
                for scope in Scope.provider_priority()
                if by_scope.get(scope)
            )

        def select_definition(
            consumer: Spec,
            requested_resource: str,
            *,
            scopes: frozenset[Scope] | None = None,
        ) -> LoadedResourceDef:
            directory = consumer_dir(consumer)
            allowed_scopes = (
                frozenset(Scope.provider_priority())
                if scopes is None
                else scopes
            )
            candidate_scopes = tuple(
                scope
                for scope in available_scopes(requested_resource)
                if scope in allowed_scopes
            )
            if not candidate_scopes:
                available = available_scopes(requested_resource)
                if isinstance(consumer, ResourceSpec) and available:
                    msg = (
                        f"{consumer.scope.value}-scoped resource "
                        f"'{consumer.name}' cannot depend on "
                        f"{available[0].value}-scoped resource "
                        f"'{requested_resource}'."
                    )
                else:
                    msg = f"Unknown resource: {requested_resource}"
                raise ValueError(msg)
            cache_key = (requested_resource, directory, candidate_scopes)
            if cache_key in select_cache:
                return select_cache[cache_key]

            for scope in candidate_scopes:
                candidates, fallback = selection_plan(
                    requested_resource,
                    scope,
                )
                if directory is None:
                    select_cache[cache_key] = fallback
                    return fallback
                for provider_dir, definition in candidates:
                    if directory.is_relative_to(provider_dir):
                        select_cache[cache_key] = definition
                        return definition
                select_cache[cache_key] = fallback
                return fallback
            select_cache[cache_key] = fallback
            return fallback

        def compile_definition(definition: LoadedResourceDef) -> ResourceSpec:
            spec = definition.spec
            if spec in built:
                return spec
            if spec in resolving_set:
                msg = "Circular resource dependency detected"
                raise RuntimeError(msg)

            resolving.append(spec)
            resolving_set.add(spec)
            selected_dependencies = tuple(
                select_definition(
                    consumer=spec,
                    requested_resource=dependency,
                    scopes=spec.scope.dependency_scopes,
                )
                for dependency in definition.dependencies
            )
            dependencies = tuple(
                compile_definition(dependency)
                for dependency in selected_dependencies
            )
            resolving.pop()
            resolving_set.remove(spec)
            dependencies_by_resource[spec] = dependencies
            built.add(spec)
            return spec

        def dependency_closure(spec: ResourceSpec) -> tuple[ResourceSpec, ...]:
            if spec in closure_cache:
                return closure_cache[spec]

            ordered: list[ResourceSpec] = []
            seen: set[ResourceSpec] = set()
            for dependency in dependencies_by_resource[spec]:
                for dep_spec in dependency_closure(dependency):
                    if dep_spec in seen:
                        continue
                    seen.add(dep_spec)
                    ordered.append(dep_spec)
            ordered.append(spec)
            closure_cache[spec] = compiled = tuple(ordered)
            return compiled

        def resolution_order(
            roots: tuple[ResourceSpec, ...],
        ) -> tuple[ResourceSpec, ...]:
            ordered: list[ResourceSpec] = []
            seen: set[ResourceSpec] = set()
            for root in roots:
                for spec in dependency_closure(root):
                    if spec in seen:
                        continue
                    seen.add(spec)
                    ordered.append(spec)
            return tuple(ordered)

        for execution_id, (consumer, resource_names) in consumers.items():
            autouse_specs = (
                tuple(
                    compile_definition(definition)
                    for name in autouse_names
                    if (
                        definition := select_definition(
                            consumer=consumer,
                            requested_resource=name,
                        )
                    ).autouse
                )
                if execution_id in autouse_keys
                else ()
            )
            injections = {
                name: compile_definition(
                    select_definition(
                        consumer=consumer,
                        requested_resource=name,
                    )
                )
                for name in resource_names
            }
            roots = (*autouse_specs, *injections.values())
            order = resolution_order(roots)
            specs = set(order)
            graphs[execution_id] = ResourceGraph(
                autouse=autouse_specs,
                injections=injections,
                dependencies={
                    spec: dependencies
                    for spec, dependencies in dependencies_by_resource.items()
                    if spec in specs
                },
                resolution_order=order,
            )
        self._graphs_by_execution_id = graphs
        return graphs

    def get_graph(self, execution_id: UUID) -> ResourceGraph:
        """Return the retained compiled graph for one execution."""
        return self._graphs_by_execution_id[execution_id]

    def save_graph(
        self,
        execution_id: UUID,
        graph: ResourceGraph,
    ) -> None:
        """Store a hydrated graph for an execution."""
        self._graphs_by_execution_id[execution_id] = graph


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
    return registry.register_resource(
        fn,
        scope=scope,
        on_resolve=on_resolve,
        on_injection=on_injection,
        on_teardown=on_teardown,
        origin_fn=origin_fn,
        autouse=autouse,
        sync=sync,
    )
