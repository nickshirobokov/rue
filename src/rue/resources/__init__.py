"""Resource injection system."""

from rue.resources.models import (
    LoadedResourceDef,
    ResolverSyncSnapshot,
    ResourceSpec,
    Scope,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver


__all__ = [
    "LoadedResourceDef",
    "ResolverSyncSnapshot",
    "ResourceRegistry",
    "ResourceResolver",
    "ResourceSpec",
    "Scope",
    "registry",
    "resource",
]
