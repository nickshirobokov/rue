"""Resource injection system."""

from rue.patching import MonkeyPatch
from rue.resources.builtins import register_builtin_resources
from rue.resources.models import (
    LoadedResourceDef,
    ResolverSyncSnapshot,
    ResourceGraph,
    ResourceSpec,
    Scope,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver


register_builtin_resources(registry)


__all__ = [
    "LoadedResourceDef",
    "MonkeyPatch",
    "ResolverSyncSnapshot",
    "ResourceGraph",
    "ResourceRegistry",
    "ResourceResolver",
    "ResourceSpec",
    "Scope",
    "register_builtin_resources",
    "registry",
    "resource",
]
