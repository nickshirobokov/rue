"""Builtin resources registered by Rue itself."""

from rue.context.runtime import CURRENT_RESOURCE_TRANSACTION
from rue.patching import MonkeyPatch
from rue.resources.models import Scope
from rue.resources.registry import ResourceRegistry


def register_builtin_resources(registry: ResourceRegistry) -> None:
    """Register framework-provided resources into the given registry."""

    @registry.register_resource(scope=Scope.TEST, sync=False, builtin=True)
    def monkeypatch() -> MonkeyPatch:
        return MonkeyPatch(
            resolver=CURRENT_RESOURCE_TRANSACTION.get().resolver,
            scope=Scope.TEST,
        )
