"""Builtin resources registered by Rue itself."""

from collections.abc import Callable

from rue.context.scopes import Scope
from rue.environment.builtin import (
    make_environment_factory,
    on_injection as environment_on_injection,
    on_resolve as environment_on_resolve,
)
from rue.patching import MonkeyPatch
from rue.resources.registry import ResourceRegistry


def register_builtin_resources(registry: ResourceRegistry) -> None:
    """Register framework-provided resources into the given registry."""

    def scoped_monkeypatch(scope: Scope) -> Callable[[], MonkeyPatch]:
        def monkeypatch() -> MonkeyPatch:
            return MonkeyPatch.for_scope(scope)

        return monkeypatch

    for scope in Scope:
        registry.register_resource(
            scoped_monkeypatch(scope),
            scope=scope,
            builtin=True,
        )
        registry.register_resource(
            make_environment_factory(scope),
            scope=scope,
            builtin=True,
            subprocess_sync=True,
            on_resolve=environment_on_resolve,
            on_injection=environment_on_injection,
        )
