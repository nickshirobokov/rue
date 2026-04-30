"""Builtin resources registered by Rue itself."""

from collections.abc import Callable

from rue.context.scopes import Scope
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
            sync=False,
            builtin=True,
        )
