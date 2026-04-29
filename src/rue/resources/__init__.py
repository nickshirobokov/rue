"""Resource injection system."""

from rue.patching import MonkeyPatch
from rue.resources.builtins import register_builtin_resources
from rue.resources.models import (
    LoadedResourceDef,
    DIGraph,
    ResolverSyncSnapshot,
    ResourceSpec,
    Scope,
)
from rue.resources.registry import ResourceRegistry, registry, resource
from rue.resources.resolver import ResourceResolver
from rue.resources.state import (
    ResourceCacheKey,
    ResolverLifecycleMode,
    ResolverExecutionContext,
    ResolverScopeOwner,
    ResolverState,
    ResourceTeardownRecord,
)


register_builtin_resources(registry)


__all__ = [
    "LoadedResourceDef",
    "MonkeyPatch",
    "DIGraph",
    "ResolverExecutionContext",
    "ResolverLifecycleMode",
    "ResolverSyncSnapshot",
    "ResolverScopeOwner",
    "ResourceRegistry",
    "ResourceResolver",
    "ResourceCacheKey",
    "ResourceSpec",
    "ResolverState",
    "ResourceTeardownRecord",
    "Scope",
    "register_builtin_resources",
    "registry",
    "resource",
]
