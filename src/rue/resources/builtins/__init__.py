"""Builtin resources registered by Rue itself."""

from rue.context.runtime import CURRENT_RESOURCE_TRANSACTION
from rue.patching import MonkeyPatch
from rue.resources.models import Scope
from rue.resources.registry import ResourceRegistry


def register_builtin_resources(registry: ResourceRegistry) -> None:
    """Register framework-provided resources into the given registry."""

    @registry.register_resource(scope=Scope.TEST, sync=False, builtin=True)
    def monkeypatch() -> MonkeyPatch:
        transaction = CURRENT_RESOURCE_TRANSACTION.get()
        return MonkeyPatch(
            lifetime=transaction.resolver.patch_lifetime(
                Scope.TEST,
                consumer_spec=transaction.consumer_spec,
            ),
        )
