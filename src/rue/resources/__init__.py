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
    "ResourceSpec",
    "ResourceRegistry",
    "ResourceResolver",
    "Scope",
    "registry",
    "resource",
]
