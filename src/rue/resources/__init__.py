"""Resource injection system."""

from rue.resources.models import (
    ResourceBlueprint,
    ResourceDef,
    ResourceIdentity,
    ResourceTransferEntry,
    Scope,
    TransferStrategy,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver


__all__ = [
    "ResourceBlueprint",
    "ResourceDef",
    "ResourceIdentity",
    "ResourceRegistry",
    "ResourceResolver",
    "ResourceTransferEntry",
    "Scope",
    "TransferStrategy",
    "registry",
    "resource",
]
