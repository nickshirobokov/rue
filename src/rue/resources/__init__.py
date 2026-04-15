"""Resource injection system."""

from rue.resources.models import ResourceDef, ResourceIdentity, Scope
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver


__all__ = [
    "ResourceDef",
    "ResourceIdentity",
    "ResourceRegistry",
    "ResourceResolver",
    "Scope",
    "registry",
    "resource",
]
