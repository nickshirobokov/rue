"""Resource injection system."""

from rue.resources.models import (
    LoadedResourceDef,
    ResourceBlueprint,
    ResourceSpec,
    Scope,
    TransferStrategy,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver


__all__ = [
    "LoadedResourceDef",
    "ResourceBlueprint",
    "ResourceSpec",
    "ResourceRegistry",
    "ResourceResolver",
    "Scope",
    "TransferStrategy",
    "registry",
    "resource",
]
