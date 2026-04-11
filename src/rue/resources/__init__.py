"""Resource injection system."""

from rue.resources.registry import (
    ResourceDef,
    ResourceIdentity,
    Scope,
    ResourceRegistry,
    registry,
    resource,
)
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

from rue.resources import builtins
