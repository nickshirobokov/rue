"""Resource registry and registration APIs."""

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class Scope(Enum):
    """Resource lifecycle scope."""

    CASE = "case"  # Fresh instance per test
    SUITE = "suite"  # Shared across tests in same file
    SESSION = "session"  # Shared across entire test run


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


@dataclass(frozen=True, slots=True)
class SelectedResource:
    """Selected resource provider for one resolution request."""

    definition: ResourceDef
    provider_dir: Path | None = None


class ResourceRegistry:
    """Registry of resource definitions and lookup rules."""

    def __init__(self) -> None:
        self._definitions: dict[str, ResourceDef] = {}
        self._session_definitions: dict[str, list[ResourceDef]] = {}
        self._builtin_definitions: dict[str, ResourceDef] = {}
        self._builtin_session_definitions: dict[str, list[ResourceDef]] = {}

    @staticmethod
    def _resource_origin(
        fn: Callable[..., Any],
    ) -> tuple[Path | None, Path | None]:
        filename = fn.__code__.co_filename
        if filename.startswith("<") and filename.endswith(">"):
            return None, None

        path = Path(filename).resolve()
        return path, path.parent

    def _require(self, name: str) -> ResourceDef:
        definition = self._definitions.get(name)
        if definition is None:
            msg = f"Unknown resource: {name}"
            raise ValueError(msg)
        return definition

    def _register(self, definition: ResourceDef) -> None:
        if definition.scope == Scope.SESSION:
            session_defs = self._session_definitions.setdefault(
                definition.name, []
            )
            session_defs.append(definition)

            current = self._definitions.get(definition.name)
            if current is None or current.scope == Scope.SESSION:
                self._definitions[definition.name] = definition
            return

        self._definitions[definition.name] = definition

    def resource(
        self,
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

            signature = inspect.signature(fn)
            dependencies = [
                parameter
                for parameter in signature.parameters
                if parameter != "self"
            ]
            is_async = inspect.iscoroutinefunction(fn)
            is_async_generator = inspect.isasyncgenfunction(fn)
            is_generator = inspect.isgeneratorfunction(fn)
            origin_path, origin_dir = self._resource_origin(fn)

            definition = ResourceDef(
                name=fn.__name__,
                fn=fn,
                scope=scope,
                is_async=is_async or is_async_generator,
                is_generator=is_generator,
                is_async_generator=is_async_generator,
                dependencies=dependencies,
                on_resolve=on_resolve,
                on_injection=on_injection,
                on_teardown=on_teardown,
                origin_path=origin_path,
                origin_dir=origin_dir,
            )
            self._register(definition)
            return fn

        if fn is not None:
            return decorator(fn)
        return decorator

    def get(self, name: str) -> ResourceDef | None:
        """Return the flat definition registered under the given name."""
        return self._definitions.get(name)

    def mark_builtin(self, name: str) -> None:
        """Preserve the current resource under the given name across resets."""
        self._builtin_definitions[name] = self._require(name)
        if name in self._session_definitions:
            self._builtin_session_definitions[name] = list(
                self._session_definitions[name]
            )
            return
        self._builtin_session_definitions.pop(name, None)

    def reset(self) -> None:
        """Reset to builtin registrations only."""
        self._definitions.clear()
        self._definitions.update(self._builtin_definitions)
        self._session_definitions.clear()
        self._session_definitions.update(
            {
                name: list(definitions)
                for name, definitions in self._builtin_session_definitions.items()
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
            and name not in self._session_definitions
        ):
            msg = f"Unknown resource: {name}"
            raise ValueError(msg)

        definition = self._definitions.get(name)
        if definition is not None and definition.scope != Scope.SESSION:
            return SelectedResource(definition=definition)

        selected: ResourceDef | None = None
        selected_depth = -1
        if request_path is not None:
            request_dir = request_path.resolve().parent
            for session_definition in self._session_definitions.get(name, []):
                if session_definition.origin_dir is None:
                    continue
                if not request_dir.is_relative_to(
                    session_definition.origin_dir
                ):
                    continue
                depth = len(session_definition.origin_dir.parts)
                if depth >= selected_depth:
                    selected = session_definition
                    selected_depth = depth

        if selected is not None:
            return SelectedResource(
                definition=selected,
                provider_dir=selected.origin_dir,
            )

        return SelectedResource(definition=self._require(name))


registry = ResourceRegistry()


def resource(
    fn: Callable[P, T] | None = None,
    *,
    scope: Scope | str = Scope.CASE,
    on_resolve: Callable[[Any], Any] | None = None,
    on_injection: Callable[[Any], Any] | None = None,
    on_teardown: Callable[[Any], Any] | None = None,
) -> Any:
    """Register a function as a resource in the default registry."""
    return registry.resource(
        fn,
        scope=scope,
        on_resolve=on_resolve,
        on_injection=on_injection,
        on_teardown=on_teardown,
    )
