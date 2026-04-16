"""Resource registry and registration APIs."""

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from rue.resources.models import (
    LoadedResourceDef,
    ResourceSpec,
    Scope,
    SelectedResource,
)

P = ParamSpec("P")
T = TypeVar("T")
_RECEIVER_PARAMETER_NAMES = {"self", "cls"}


class ResourceRegistry:
    """Registry of resource definitions and lookup rules."""

    def __init__(self) -> None:
        self._definitions: dict[str, LoadedResourceDef] = {}
        self._process_definitions: dict[str, list[LoadedResourceDef]] = {}
        self._builtin_definitions: dict[str, LoadedResourceDef] = {}
        self._builtin_process_definitions: dict[str, list[LoadedResourceDef]] = {}

    @staticmethod
    def _resource_origin(
        fn: Callable[..., Any],
    ) -> tuple[Path | None, Path | None]:
        filename = fn.__code__.co_filename
        if filename.startswith("<") and filename.endswith(">"):
            return None, None

        path = Path(filename).resolve()
        return path, path.parent

    def _require(self, name: str) -> LoadedResourceDef:
        definition = self._definitions.get(name)
        if definition is None:
            msg = f"Unknown resource: {name}"
            raise ValueError(msg)
        return definition

    def _register(self, definition: LoadedResourceDef) -> None:
        ident = definition.spec
        if ident.scope == Scope.PROCESS:
            process_defs = self._process_definitions.setdefault(
                ident.name, []
            )
            process_defs.append(definition)

            current = self._definitions.get(ident.name)
            if current is None or current.spec.scope == Scope.PROCESS:
                self._definitions[ident.name] = definition
            return

        self._definitions[ident.name] = definition

    def resource(
        self,
        fn: Callable[P, T] | None = None,
        *,
        scope: Scope | str = Scope.TEST,
        on_resolve: Callable[[Any], Any] | None = None,
        on_injection: Callable[[Any], Any] | None = None,
        on_teardown: Callable[[Any], Any] | None = None,
        origin_fn: Callable[..., Any] | None = None,
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
            origin_path, origin_dir = self._resource_origin(origin_fn or fn)

            definition = LoadedResourceDef(
                spec=ResourceSpec(
                    name=fn.__name__,
                    scope=scope,
                    provider_path=str(origin_path)
                    if origin_path is not None
                    else None,
                    provider_dir=str(origin_dir)
                    if origin_dir is not None
                    else None,
                    dependencies=tuple(dependencies),
                ),
                fn=fn,
                is_async=is_async or is_async_generator,
                is_generator=is_generator,
                is_async_generator=is_async_generator,
                on_resolve=on_resolve,
                on_injection=on_injection,
                on_teardown=on_teardown,
            )
            self._register(definition)
            return fn

        if fn is not None:
            return decorator(fn)
        return decorator

    def get(self, name: str) -> LoadedResourceDef | None:
        """Return the flat definition registered under the given name."""
        return self._definitions.get(name)

    def mark_builtin(self, name: str) -> None:
        """Preserve the current resource under the given name across resets."""
        self._builtin_definitions[name] = self._require(name)
        if name in self._process_definitions:
            self._builtin_process_definitions[name] = list(
                self._process_definitions[name]
            )
            return
        self._builtin_process_definitions.pop(name, None)

    def reset(self) -> None:
        """Reset to builtin registrations only."""
        self._definitions.clear()
        self._definitions.update(self._builtin_definitions)
        self._process_definitions.clear()
        self._process_definitions.update(
            {
                name: list(definitions)
                for name, definitions in self._builtin_process_definitions.items()
            }
        )

    def select(
        self,
        name: str,
        request_path: Path | None,
    ) -> SelectedResource:
        """Select the active definition for one DI lookup."""
        if (
            name not in self._definitions
            and name not in self._process_definitions
        ):
            msg = f"Unknown resource: {name}"
            raise ValueError(msg)

        definition = self._definitions.get(name)
        if definition is not None and definition.spec.scope != Scope.PROCESS:
            return SelectedResource(definition=definition)

        selected: LoadedResourceDef | None = None
        selected_depth = -1
        if request_path is not None:
            request_dir = request_path.resolve().parent
            for process_definition in self._process_definitions.get(name, []):
                origin_dir = process_definition.spec.origin_dir
                if origin_dir is None:
                    continue
                if not request_dir.is_relative_to(origin_dir):
                    continue
                depth = len(origin_dir.parts)
                if depth >= selected_depth:
                    selected = process_definition
                    selected_depth = depth

        if selected is not None:
            return SelectedResource(definition=selected)

        definition = self._require(name)
        return SelectedResource(definition=definition)


registry = ResourceRegistry()


def resource(
    fn: Callable[P, T] | None = None,
    *,
    scope: Scope | str = Scope.TEST,
    on_resolve: Callable[[Any], Any] | None = None,
    on_injection: Callable[[Any], Any] | None = None,
    on_teardown: Callable[[Any], Any] | None = None,
    origin_fn: Callable[..., Any] | None = None,
) -> Any:
    """Register a function as a resource in the default registry."""
    return registry.resource(
        fn,
        scope=scope,
        on_resolve=on_resolve,
        on_injection=on_injection,
        on_teardown=on_teardown,
        origin_fn=origin_fn,
    )
