"""Resource injection system."""

from rue.resources.models import (
    LoadedResourceDef,
    ResolverSnapshot,
    ResourceSpec,
    Scope,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver


__all__ = [
    "LoadedResourceDef",
    "ResolverSnapshot",
    "ResourceRegistry",
    "ResourceResolver",
    "ResourceSpec",
    "Scope",
    "registry",
    "resource",
]
