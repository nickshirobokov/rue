"""Resource injection system."""

from rue.patching import MonkeyPatch
from rue.resources.builtins import register_builtin_resources
from rue.resources.models import (
    DIGraph,
    LoadedResourceDef,
    ResourceSpec,
    ResourceTransferSnapshot,
    Scope,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver
from rue.resources.state import (
    ResolverExecutionContext,
    ResolverLifecycleMode,
    ResolverScopeOwner,
    ResolverState,
    ResourceCacheKey,
    ResourceTeardownRecord,
    ResourceTransferState,
)
from rue.resources.transfer import ResourceTransfer


register_builtin_resources(registry)


__all__ = [
    "DIGraph",
    "LoadedResourceDef",
    "MonkeyPatch",
    "ResolverExecutionContext",
    "ResolverLifecycleMode",
    "ResolverScopeOwner",
    "ResolverState",
    "ResourceCacheKey",
    "ResourceRegistry",
    "ResourceResolver",
    "ResourceSpec",
    "ResourceTeardownRecord",
    "ResourceTransfer",
    "ResourceTransferSnapshot",
    "ResourceTransferState",
    "Scope",
    "register_builtin_resources",
    "registry",
    "resource",
]
