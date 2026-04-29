"""Builtin resources registered by Rue itself."""

from collections.abc import Callable

from rue.context.scopes import Scope
from rue.context.runtime import CURRENT_RESOURCE_TRANSACTION
from rue.patching import MonkeyPatch
from rue.resources.registry import ResourceRegistry


def register_builtin_resources(registry: ResourceRegistry) -> None:
    """Register framework-provided resources into the given registry."""

    def scoped_monkeypatch(scope: Scope) -> Callable[[], MonkeyPatch]:
        def monkeypatch() -> MonkeyPatch:
            transaction = CURRENT_RESOURCE_TRANSACTION.get()
            return MonkeyPatch(
                lifetime=transaction.resolver.patch_lifetime(scope),
            )

        return monkeypatch

    for scope in Scope:
        registry.register_resource(
            scoped_monkeypatch(scope),
            scope=scope,
            sync=False,
            builtin=True,
        )
