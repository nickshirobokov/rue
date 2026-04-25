"""Builtin resources registered by Rue itself."""

from rue.patching import MonkeyPatch
from rue.resources.models import Scope
from rue.resources.registry import ResourceRegistry


def register_builtin_resources(registry: ResourceRegistry) -> None:
    """Register framework-provided resources into the given registry."""

    @registry.resource(scope=Scope.TEST, sync=False)
    def monkeypatch() -> MonkeyPatch:
        return MonkeyPatch(scope=Scope.TEST)

    registry.mark_builtin("monkeypatch")
